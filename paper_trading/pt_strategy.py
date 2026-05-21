"""
Paper Trading 策略 — 轻量版（仅用腾讯实时行情，无需 yfinance）

信号逻辑:
  - 买入: 腾讯实时价 ≤ EMA 慢线(日线) 且 腾讯价相对昨日收盘跌幅>2% → 超跌反弹
  - 卖出: 盈利>3% 或 亏损>2%止损
  - 首次启动时通过 yfinance 拉取一次日线基准，后续只用腾讯实时价
"""

import os, sys, logging, time
import pandas as pd
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np

from universe import SYMBOLS, SYMBOL_NAMES

logger = logging.getLogger(__name__)

# ── 参数 ──────────────────────────────────────────────────────────────────────
MAX_POSITIONS    = 8
POSITION_PCT     = 0.10    # 每笔 10%
TAKE_PROFIT_PCT  = 0.03    # 盈利 3% 止盈
STOP_LOSS_PCT    = 0.02    # 亏损 2% 止损
PRICE_BUFFER: dict[str, list] = {}  # {symbol: [prices]}
BUFFER_MAX       = 30      # 最多保留 30 个价格点

# ── 日线基准（启动时通过 yfinance 拉取一次）──────────────────────────────────
_daily_ref: dict[str, dict] = {}  # {symbol: {close, ema20, rsi14, atr14}}


def _to_yf(sym: str) -> str:
    return f'{sym}.SS' if sym.startswith('6') else f'{sym}.SZ'


def warmup_daily_ref():
    """利用 yfinance 拉取一次日线基准数据（启动时调用，只跑一次）"""
    import yfinance as yf
    global _daily_ref
    batch_size = 30
    all_syms = SYMBOLS

    for i in range(0, len(all_syms), batch_size):
        batch = all_syms[i:i+batch_size]
        tickers = ' '.join(_to_yf(s) for s in batch)
        try:
            df = yf.download(tickers, period='3mo', interval='1d',
                             progress=False, auto_adjust=True, group_by='ticker')
            for sym in batch:
                try:
                    tk = _to_yf(sym)
                    if tk in df and not df[tk].empty:
                        d = df[tk]
                        close = d['Close'].astype(float)
                        ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
                        # 简单 RSI(14)
                        delta = close.diff()
                        gain = delta.clip(lower=0).ewm(span=14, adjust=False).mean().iloc[-1]
                        loss = (-delta).clip(lower=0).ewm(span=14, adjust=False).mean().iloc[-1]
                        rs = gain / loss if loss > 0 else float('inf')
                        rsi = 100 - 100/(1+rs) if loss > 0 else 100.0
                        # ATR(14)
                        h, l, c = d['High'].astype(float), d['Low'].astype(float), close
                        tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
                        atr = tr.ewm(span=14, adjust=False).mean().iloc[-1]
                        _daily_ref[sym] = {
                            'close': float(close.iloc[-1]),
                            'ema20': float(ema20),
                            'rsi14': float(rsi),
                            'atr14': float(atr),
                        }
                except Exception:
                    pass
            logger.info(f"日线基准: {len(_daily_ref)}/{len(all_syms)} 已加载")
        except Exception as e:
            logger.warning(f"yfinance批量拉取失败 batch={i}: {e}")
            # 逐个 fallback
            for sym in batch:
                try:
                    tk = _to_yf(sym)
                    df = yf.download(tk, period='3mo', interval='1d', progress=False, auto_adjust=True)
                    if df is not None and len(df) > 30:
                        if isinstance(df.columns, pd.MultiIndex):
                            df.columns = df.columns.droplevel(1)
                        close = df['Close'].astype(float)
                        ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
                        delta = close.diff()
                        gain = delta.clip(lower=0).ewm(span=14, adjust=False).mean().iloc[-1]
                        loss = (-delta).clip(lower=0).ewm(span=14, adjust=False).mean().iloc[-1]
                        rs = gain / loss if loss > 0 else float('inf')
                        rsi = 100 - 100/(1+rs) if loss > 0 else 100.0
                        h = df['High'].astype(float); l = df['Low'].astype(float)
                        tr = pd.concat([h-l,(h-close.shift()).abs(),(l-close.shift()).abs()],axis=1).max(axis=1)
                        atr = float(tr.ewm(span=14,adjust=False).mean().iloc[-1])
                        _daily_ref[sym] = {'close':float(close.iloc[-1]), 'ema20':ema20, 'rsi14':rsi, 'atr14':atr}
                except Exception:
                    pass
    logger.info(f"日线基准加载完成: {len(_daily_ref)}/{len(all_syms)} 只")


def add_quote(symbol: str, price: float):
    """将实时行情加入缓冲区"""
    if symbol not in PRICE_BUFFER:
        PRICE_BUFFER[symbol] = []
    PRICE_BUFFER[symbol].append(price)
    if len(PRICE_BUFFER[symbol]) > BUFFER_MAX:
        PRICE_BUFFER[symbol].pop(0)


def evaluate(engine, symbol: str) -> str:
    """
    评估单个标的（纯实时行情驱动，不依赖 yfinance）
    返回 'buy' / 'sell' / 'hold'
    """
    # 获取实时价格
    with engine.lock:
        price = engine.latest_prices.get(symbol, 0)
        npos = len(engine.positions)
        pos = engine.positions.get(symbol)

    if price <= 0:
        return 'hold'

    add_quote(symbol, price)
    ref = _daily_ref.get(symbol)

    # ── 卖出逻辑 ──
    if pos:
        cost = pos.get('avg_cost', price)
        gain_pct = (price - cost) / cost if cost > 0 else 0

        # 止盈
        if gain_pct >= TAKE_PROFIT_PCT:
            logger.info(f"[{symbol}] 止盈: +{gain_pct:.1%}")
            return 'sell'
        # 止损
        if gain_pct <= -STOP_LOSS_PCT:
            logger.info(f"[{symbol}] 止损: {gain_pct:.1%}")
            return 'sell'
        return 'hold'

    # ── 买入逻辑 ──
    if npos >= MAX_POSITIONS:
        return 'hold'

    # 需要日线基准
    if ref is None:
        return 'hold'

    ema20 = ref['ema20']
    rsi = ref['rsi14']

    # ═══ P0 修复：趋势过滤 — 价格必须在 EMA20 上方才允许买入 ═══
    # 避免在下跌趋势中反复抄底（"接飞刀"亏损模式）
    if price < ema20:
        return 'hold'

    score = 0
    reasons = []

    # RSI 超卖 + 趋势确认 = 超跌反弹机会
    if rsi < 30:
        score += 40
        reasons.append(f'RSI={rsi:.1f}')
    elif rsi < 40:
        score += 20
        reasons.append(f'RSI={rsi:.1f}(偏弱)')

    # EMA 确认（价格刚站上 EMA20 = 趋势转好信号）
    if ema20 > 0 and price > ema20:
        premium = (price - ema20) / ema20
        if premium < 0.03:  # 刚突破，不是追高
            score += 15
            reasons.append(f'突破EMA20(+{premium:.1%})')

    # 日内短周期超跌：当前价 < 近10个实时价均值的 98%
    buf = PRICE_BUFFER.get(symbol, [price])
    if len(buf) >= 5:
        avg10 = np.mean(buf[-min(10, len(buf)):])
        if price < avg10 * 0.98:
            score += 15
            reasons.append(f'日内超跌')

    if score >= 40:
        logger.info(f"[{symbol}] 买入信号: {' | '.join(reasons)} score={score:.0f}")
        return 'buy'

    return 'hold'


def run_strategy(engine):
    """遍历全市场，执行策略"""
    # 先把行情缓冲
    with engine.lock:
        for sym, px in engine.latest_prices.items():
            if px > 0:
                add_quote(sym, px)

    # 收集买入候选
    candidates = []
    for symbol in SYMBOLS:
        try:
            sig = evaluate(engine, symbol)
            if sig == 'buy':
                # 计算简单评分
                ref = _daily_ref.get(symbol)
                score = 0
                if ref:
                    score = max(0, (30 - ref['rsi14']) * 2) + (ref['ema20'] / max(ref['close'], 0.01) - 1) * 100
                candidates.append((symbol, score))
            elif sig == 'sell':
                engine.sell(symbol)
        except Exception as e:
            logger.debug(f"评估{symbol}: {e}")

    candidates.sort(key=lambda x: x[1], reverse=True)

    with engine.lock:
        slots = MAX_POSITIONS - len(engine.positions)

    portfolio_val = engine.total_value()

    for symbol, score in candidates[:slots]:
        try:
            with engine.lock:
                price = engine.latest_prices.get(symbol, 0)
            if price <= 0:
                continue
            amount = portfolio_val * POSITION_PCT
            result = engine.buy(symbol, amount)
            if result:
                with engine.lock:
                    if symbol in engine.positions:
                        engine.positions[symbol]['stop_loss'] = round(price * (1 - STOP_LOSS_PCT), 2)
                logger.info(f"BUY {symbol} {SYMBOL_NAMES.get(symbol,'')} @{price:.2f}")

            with engine.lock:
                slots = MAX_POSITIONS - len(engine.positions)
            if slots <= 0:
                break
        except Exception as e:
            logger.error(f"买入{symbol}: {e}")
