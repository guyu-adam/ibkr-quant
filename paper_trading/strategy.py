"""RSI + EMA 动量策略"""

import datetime
import logging
import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

SYMBOLS = ['000001', '600519', '300750', '000858', '601318']

RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
EMA_FAST = 10
EMA_SLOW = 30
ATR_PERIOD = 14
ATR_STOP_MULT = 2.0
POSITION_PCT = 0.02          # 每次用 2% 资金
MAX_POSITIONS = 5


def _rsi(closes, period=RSI_PERIOD):
    delta = np.diff(closes, prepend=closes[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = pd.Series(gain).ewm(alpha=1/period, adjust=False).mean().values
    avg_loss = pd.Series(loss).ewm(alpha=1/period, adjust=False).mean().values
    rs = np.divide(avg_gain, avg_loss, out=np.full_like(avg_gain, float('inf')), where=avg_loss != 0)
    return 100.0 - 100.0 / (1.0 + rs)


def _ema(series, period):
    return pd.Series(series).ewm(span=period, adjust=False).mean().values


def _atr(high, low, close, period=ATR_PERIOD):
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    return pd.Series(tr).ewm(alpha=1/period, adjust=False).mean().values


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

    close = df['收盘'].values.astype(float)
    high = df['最高'].values.astype(float)
    low = df['最低'].values.astype(float)

    rsi_vals = _rsi(close)
    ema_fast = _ema(close, EMA_FAST)
    ema_slow = _ema(close, EMA_SLOW)
    atr_vals = _atr(high, low, close)

    latest_rsi = rsi_vals[-1]
    latest_close = close[-1]
    prev_ema_slow = ema_slow[-2] if len(ema_slow) > 1 else ema_slow[-1]
    latest_ema_slow = ema_slow[-1]
    latest_atr = atr_vals[-1]

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
