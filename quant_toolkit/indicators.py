"""
Technical indicators — thin wrappers around the `ta` library.
Each function accepts a pd.Series and returns a pd.Series.
"""

import pandas as pd
import ta


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index."""
    return ta.momentum.RSIIndicator(close=close, window=period).rsi()


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD line, signal line, and histogram.

    Returns a DataFrame with columns: macd, signal, histogram
    """
    macd_obj = ta.trend.MACD(
        close=close, window_slow=slow, window_fast=fast, window_sign=signal
    )
    return pd.DataFrame({
        "macd":      macd_obj.macd(),
        "signal":    macd_obj.macd_signal(),
        "histogram": macd_obj.macd_diff(),
    })


def ema(close: pd.Series, period: int = 20) -> pd.Series:
    """Exponential Moving Average."""
    return ta.trend.EMAIndicator(close=close, window=period).ema_indicator()


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range."""
    return ta.volatility.AverageTrueRange(
        high=high, low=low, close=close, window=period
    ).average_true_range()


def bollinger_bands(close: pd.Series, period: int = 20, nbdev: int = 2) -> pd.DataFrame:
    """Bollinger Bands.

    Returns a DataFrame with columns: upper, middle, lower, bandwidth, percent_b
    """
    bb = ta.volatility.BollingerBands(
        close=close, window=period, window_dev=nbdev
    )
    return pd.DataFrame({
        "upper":      bb.bollinger_hband(),
        "middle":     bb.bollinger_mavg(),
        "lower":      bb.bollinger_lband(),
        "bandwidth":  bb.bollinger_wband(),
        "percent_b":  bb.bollinger_pband(),
    })


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume."""
    return ta.volume.OnBalanceVolumeIndicator(
        close=close, volume=volume
    ).on_balance_volume()
