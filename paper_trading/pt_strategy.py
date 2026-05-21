"""
Paper Trading 策略适配层 — 使用独立的 strategy.mean_reversion 策略
不包含策略逻辑，只负责将 paper_trading engine 与策略对接
"""

import os, sys, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.data_feed import CachedFeed, TencentFeed
from strategy.mean_reversion import MeanReversionStrategy, PositionSizer
from universe import SYMBOLS

logger = logging.getLogger(__name__)

# ── 初始化数据源和策略（全局单例）──────────────────────────────────────────────
_data_feed = CachedFeed(
    TencentFeed(disable_proxy=os.environ.get("DISABLE_PROXY", "0") == "1"),
    ttl_seconds=300,
)

_strategy = MeanReversionStrategy({
    'rsi_period': 14, 'rsi_oversold': 30, 'rsi_overbought': 70,
    'atr_period': 14, 'atr_stop_mult': 2.0,
    'macd_fast': 12, 'macd_slow': 26, 'macd_signal': 9,
    'vol_lookback': 20, 'vol_spike_ratio': 1.2,
    'min_score': 30, 'take_profit_pct': 0.05, 'hard_stop_pct': 0.03,
    'name': 'mean_reversion',
})

_sizer = PositionSizer(base_pct=0.08, max_pct=0.15, max_positions=8)


def evaluate(engine, symbol: str) -> str:
    """
    Paper trading engine 调用入口。
    返回 'buy' / 'sell' / 'hold'（兼容旧接口）
    """
    from strategy.mean_reversion import PositionSizer

    # 读取 engine 持仓转换为策略格式
    positions = {}
    with engine.lock:
        for sym, pos in engine.positions.items():
            positions[sym] = {
                'shares': pos['shares'],
                'avg_cost': pos.get('avg_cost', 0),
                'stop_loss': pos.get('stop_loss', 0),
            }

    result = _strategy.evaluate(_data_feed, symbol, positions)

    signal = result.get('signal', 'hold')
    if signal == 'buy':
        with engine.lock:
            npos = len(engine.positions)
        if npos >= _sizer.max_positions:
            return 'hold'
        # 检查该 symbol 是否已在持仓中
        if symbol in positions:
            return 'hold'
        return 'buy'
    elif signal == 'sell':
        if symbol in positions:
            return 'sell'
    elif signal == 'hold' and result.get('new_stop') and symbol in positions:
        # 更新移动止损
        with engine.lock:
            if symbol in engine.positions:
                old = engine.positions[symbol].get('stop_loss', 0)
                new = result['new_stop']
                if new > old:
                    engine.positions[symbol]['stop_loss'] = round(new, 2)

    return 'hold'


def run_strategy(engine):
    """遍历全市场，执行策略信号"""
    portfolio_val = engine.total_value()

    # 收集当前持仓
    positions = {}
    with engine.lock:
        for sym, pos in engine.positions.items():
            positions[sym] = {
                'shares': pos['shares'],
                'avg_cost': pos.get('avg_cost', 0),
                'stop_loss': pos.get('stop_loss', 0),
            }

    buy_candidates = []

    for symbol in SYMBOLS:
        try:
            result = _strategy.evaluate(_data_feed, symbol, positions)
            signal = result.get('signal', 'hold')

            if signal == 'buy':
                buy_candidates.append((symbol, result['score']))
            elif signal == 'sell':
                engine.sell(symbol)
            elif result.get('new_stop') and symbol in positions:
                with engine.lock:
                    if symbol in engine.positions:
                        old = engine.positions[symbol].get('stop_loss', 0)
                        new = result['new_stop']
                        if new > old:
                            engine.positions[symbol]['stop_loss'] = round(new, 2)
        except Exception as e:
            logger.debug(f"策略评估 {symbol}: {e}")

    # 按评分排序买入最优标的
    buy_candidates.sort(key=lambda x: x[1], reverse=True)

    with engine.lock:
        npos = len(engine.positions)
        slots = _sizer.max_positions - npos

    for symbol, score in buy_candidates[:slots]:
        try:
            df = _data_feed.fetch_history(symbol)
            if df is None:
                continue
            price = float(df['close'].iloc[-1])
            high  = df['high'].astype(float)
            low   = df['low'].astype(float)
            close = df['close'].astype(float)
            atr_df = pd.DataFrame({'high': high, 'low': low, 'close': close})
            # Use strategy's ATR calculation
            atr_vals = _strategy._atr(high, low, close, _strategy.atr_period)
            cur_atr = float(atr_vals.iloc[-1])

            shares = _sizer.size(portfolio_val, price, cur_atr)
            if shares > 0:
                # 用 engine 的 buy 方法（以金额买入）
                amount = shares * price * 1.01  # 一点滑点缓冲
                engine.buy(symbol, amount)
                # 设置初始止损
                with engine.lock:
                    if symbol in engine.positions:
                        stop = _strategy.trailing_stop(symbol, price, cur_atr, price)
                        engine.positions[symbol]['stop_loss'] = round(stop, 2)

            with engine.lock:
                npos = len(engine.positions)
                slots = _sizer.max_positions - npos
            if slots <= 0:
                break
        except Exception as e:
            logger.error(f"买入 {symbol}: {e}")


# ── 辅助函数（保留给测试和外部调用）────────────────────────────────────────────
def _to_yf_ticker(symbol: str) -> str:
    return f'{symbol}.SS' if symbol.startswith('6') else f'{symbol}.SZ'
