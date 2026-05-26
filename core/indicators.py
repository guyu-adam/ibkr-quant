"""
统一指标计算 — 消除跨模块重复实现。

All indicator functions accept pd.Series and return pd.Series.
"""

import numpy as np
import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder's smoothing)."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(span=period, adjust=False).mean()
    loss = (-delta).clip(lower=0).ewm(span=period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    vals = 100.0 - 100.0 / (1.0 + rs)
    vals[loss == 0] = 100.0
    vals.iloc[:period] = np.nan
    return vals


def macd(close: pd.Series, fast: int = 12, slow: int = 26,
         signal: int = 9) -> pd.DataFrame:
    """MACD — returns DataFrame with columns: line, signal, histogram."""
    ef = close.ewm(span=fast, adjust=False).mean()
    es = close.ewm(span=slow, adjust=False).mean()
    line = ef - es
    sig = line.ewm(span=signal, adjust=False).mean()
    return pd.DataFrame({"line": line, "signal": sig, "histogram": line - sig})


def atr(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = 14) -> pd.Series:
    """Average True Range."""
    prev = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev).abs(), (low - prev).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def ema(data, period: int) -> float:
    """EMA of a list or array (for non-pandas data)."""
    if len(data) < period:
        return float(data[-1])
    alpha = 2 / (period + 1)
    result = float(data[0])
    for x in data[1:]:
        result = alpha * x + (1 - alpha) * result
    return result


def trix(close: pd.Series, period: int = 14) -> pd.Series:
    """TRIX indicator."""
    ema1 = close.ewm(span=period, adjust=False).mean()
    ema2 = ema1.ewm(span=period, adjust=False).mean()
    ema3 = ema2.ewm(span=period, adjust=False).mean()
    return ema3.pct_change()


def kdj(high: pd.Series, low: pd.Series, close: pd.Series,
        n: int = 9, m1: int = 3, m2: int = 3) -> tuple:
    """KDJ indicator — returns (K, D) series."""
    low_n, high_n = low.rolling(n).min(), high.rolling(n).max()
    rsv = (close - low_n) / (high_n - low_n + 1e-8) * 100
    k = rsv.ewm(span=m1, adjust=False).mean()
    d = k.ewm(span=m2, adjust=False).mean()
    return k, d


def bollinger_bands(close: pd.Series, period: int = 20, n_std: float = 2.0):
    """Returns (middle, upper, lower, width, position)."""
    ma = close.rolling(period).mean()
    std = close.rolling(period).std()
    width = (std * n_std) / ma
    position = (close - ma) / (std * n_std + 1e-8)
    return ma, ma + n_std * std, ma - n_std * std, width, position


def max_drawdown(close: pd.Series) -> float:
    """Maximum drawdown from peak."""
    peak = close.expanding().max()
    dd = (close - peak) / peak
    return abs(float(dd.min())) if len(dd) > 0 else 0.0


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume."""
    direction = np.sign(close.diff().fillna(0))
    return (direction * volume).cumsum()


def vwap(high: pd.Series, low: pd.Series, close: pd.Series,
         volume: pd.Series) -> pd.Series:
    """Volume-Weighted Average Price."""
    typical = (high + low + close) / 3
    return (typical * volume).cumsum() / volume.cumsum()


def adx(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = 14) -> pd.Series:
    """Average Directional Index."""
    tr = atr(high, low, close, period) * period  # un-smoothed
    up = high.diff()
    down = -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    plus_di = 100 * plus_dm.ewm(span=period, adjust=False).mean() / (tr + 1e-8)
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / (tr + 1e-8)
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di + 1e-8)) * 100
    return dx.ewm(span=period, adjust=False).mean()


def williams_r(high: pd.Series, low: pd.Series, close: pd.Series,
               period: int = 14) -> pd.Series:
    """Williams %R."""
    hh = high.rolling(period).max()
    ll = low.rolling(period).min()
    return (hh - close) / (hh - ll + 1e-8) * -100


def cci(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = 14) -> pd.Series:
    """Commodity Channel Index."""
    tp = (high + low + close) / 3
    ma = tp.rolling(period).mean()
    mad = tp.rolling(period).apply(lambda x: np.abs(x - x.mean()).mean())
    return (tp - ma) / (0.015 * mad + 1e-8)


def sortino_ratio(returns: pd.Series, period: int = 63) -> pd.Series:
    """Rolling Sortino ratio."""
    downside = returns.clip(upper=0)
    downside_std = downside.rolling(period).std()
    return returns.rolling(period).mean() / (downside_std + 1e-8)
