"""RSI + EMA 动量策略 — 使用共享指标模块确保与主系统行为一致"""

import logging
import pandas as pd
import yfinance as yf

# 共享指标实现（与主系统 strategy/signals.py 一致）
from strategy.signals import rsi as _rsi_fn, ema, atr as _atr_fn

# 集中配置
from config.settings import (
    RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT,
    MOM_FAST as EMA_FAST, MOM_SLOW as EMA_SLOW,
    ATR_PERIOD, STOP_LOSS_ATR_MULT as ATR_STOP_MULT,
)

logger = logging.getLogger(__name__)

SYMBOLS = ['000001', '600519', '300750', '000858', '601318']
POSITION_PCT = 0.02   # 每次用 2% 资金
MAX_POSITIONS = 5


def _to_yf_ticker(symbol):
    """A股代码映射成 yfinance ticker: 6开头→.SS, 其他→.SZ"""
    return f'{symbol}.SS' if symbol.startswith('6') else f'{symbol}.SZ'


def fetch_history(symbol, days=120):
    """通过 yfinance 获取日线历史数据（走国际接口，不经东方财富）"""
    import time as _time
    ticker = _to_yf_ticker(symbol)
    for attempt in range(3):
        try:
            df = yf.download(ticker, period="6mo", interval="1d", progress=False, auto_adjust=True)
            if df is not None and len(df) >= RSI_PERIOD + 10:
                break
            if attempt < 2:
                _time.sleep(2)
        except Exception as e:
            logger.error(f"获取{symbol}历史数据失败 (attempt {attempt+1}): {e}")
            if attempt < 2:
                _time.sleep(2)
    else:
        logger.warning(f"{symbol} 历史数据不足")
        return None

    # yfinance 返回 MultiIndex columns (Price, Ticker)，去掉ticker层
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    df = df.reset_index()
    df.rename(columns={'Date': '日期', 'Open': '开盘', 'Close': '收盘',
                       'High': '最高', 'Low': '最低', 'Volume': '成交量'}, inplace=True)
    for col in ['开盘', '收盘', '最高', '最低']:
        df[col] = df[col].astype(float)
    return df


def evaluate(engine, symbol):
    """评估单个标的，返回 'buy' / 'sell' / 'hold'"""
    df = fetch_history(symbol)
    if df is None:
        return 'hold'

    close = df['收盘']
    high = df['最高']
    low = df['最低']

    # 使用共享模块的指标函数（与主系统完全一致）
    rsi_vals = _rsi_fn(close, RSI_PERIOD)
    ema_fast = ema(close, EMA_FAST)
    ema_slow = ema(close, EMA_SLOW)
    # atr 需要 DataFrame，构建一个
    atr_df = pd.DataFrame({"high": high, "low": low, "close": close})
    atr_vals = _atr_fn(atr_df, ATR_PERIOD)

    latest_rsi = float(rsi_vals.iloc[-1])
    latest_close = float(close.iloc[-1])
    prev_ema_slow = float(ema_slow.iloc[-2]) if len(ema_slow) > 1 else float(ema_slow.iloc[-1])
    latest_ema_slow = float(ema_slow.iloc[-1])
    latest_atr = float(atr_vals.iloc[-1])

    if pd.isna(latest_rsi) or pd.isna(latest_atr):
        return 'hold'

    uptrend = latest_close > latest_ema_slow and latest_ema_slow > prev_ema_slow

    # ── 买入信号 ──
    if latest_rsi < RSI_OVERSOLD and uptrend:
        with engine.lock:
            npos = len(engine.positions)
        if npos < MAX_POSITIONS and symbol not in engine.positions:
            return 'buy'

    # ── 卖出信号 ──
    if symbol in engine.positions:
        with engine.lock:
            pos = engine.positions.get(symbol)
            if pos is None:
                return 'hold'
            stop = pos['stop_loss']

        # ATR 移动止损
        new_stop = latest_close - ATR_STOP_MULT * latest_atr
        if new_stop > stop:
            with engine.lock:
                if symbol in engine.positions:
                    engine.positions[symbol]['stop_loss'] = round(new_stop, 2)

        if latest_rsi > RSI_OVERBOUGHT:
            return 'sell'
        if latest_close < stop:
            return 'sell'

    return 'hold'


def run_strategy(engine):
    """遍历所有标的，发送信号"""
    for symbol in SYMBOLS:
        try:
            signal = evaluate(engine, symbol)
            if signal == 'buy':
                portfolio_val = engine.total_value()
                amount = portfolio_val * POSITION_PCT
                engine.buy(symbol, amount)
            elif signal == 'sell':
                engine.sell(symbol)
        except Exception as e:
            logger.error(f"策略评估 {symbol} 出错: {e}")
