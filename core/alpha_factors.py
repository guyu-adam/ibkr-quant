"""
Alpha 因子库 v2 — Alpha158 风格多维度因子计算

Factor categories:
  - Momentum: 1/3/6/12m returns, RSI, MACD, TRIX, KDJ
  - Volatility: realized vol, ATR ratio, skewness, kurtosis
  - Volume: volume ratio, OBV, VWAP deviation, turnover proxy
  - Technical: Bollinger Bands, EMA cross, Parabolic SAR, ADX
  - Value proxy: price/MA deviation, high-low range ratio
  - Quality proxy: Sharpe ratio, max drawdown, recovery factor

Each factor is cross-sectionally z-scored.
"""

import numpy as np
import pandas as pd


def _zscore(series: pd.Series) -> pd.Series:
    s = series.astype(float)
    mu, std = s.mean(), s.std()
    if std is None or (isinstance(std, (int, float)) and std == 0) or (hasattr(std, '__len__') and std <= 0):
        return s * 0.0
    std_val = float(std) if isinstance(std, (int, float, np.floating)) else std
    if std_val <= 0:
        return s * 0.0
    return (s - mu) / std_val


def compute_factors(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all alpha factors from OHLCV data.

    Args:
        df: DataFrame with columns [open, high, low, close, volume]
            Index must be datetime.

    Returns:
        DataFrame with factor columns, same index as input.
    """
    close  = df["close"].astype(float)
    high   = df["high"].astype(float)
    low    = df["low"].astype(float)
    volume = df["volume"].astype(float)
    returns = close.pct_change()

    factors = pd.DataFrame(index=df.index)

    # ── Momentum (12 factors) ─────────────────────────────────────────
    factors["ret_1d"]   = returns
    factors["ret_5d"]   = close.pct_change(5)
    factors["ret_21d"]  = close.pct_change(21)
    factors["ret_63d"]  = close.pct_change(63)
    factors["ret_126d"] = close.pct_change(126)
    factors["ret_252d"] = close.pct_change(252)
    factors["rsi_14"]   = _rsi(close, 14)
    factors["rsi_28"]   = _rsi(close, 28)
    factors["macd_hist"] = _macd_hist(close)
    factors["trix_14"]  = _trix(close, 14)
    factors["kdj_k"]    = _kdj(high, low, close)[0]
    factors["kdj_d"]    = _kdj(high, low, close)[1]

    # ── Volatility (8 factors) ────────────────────────────────────────
    factors["vol_5d"]   = returns.rolling(5).std()
    factors["vol_21d"]  = returns.rolling(21).std()
    factors["vol_63d"]  = returns.rolling(63).std()
    factors["atr_14"]   = _atr(high, low, close, 14) / close
    factors["skew_21d"] = returns.rolling(21).skew()
    factors["kurt_21d"] = returns.rolling(21).kurt()
    factors["hl_ratio"] = (high - low) / close
    factors["max_dd_63d"] = close.rolling(63).apply(_max_drawdown, raw=False)

    # ── Volume (6 factors) ────────────────────────────────────────────
    factors["vol_ratio_5d"]  = volume / volume.rolling(5).mean()
    factors["vol_ratio_21d"] = volume / volume.rolling(21).mean()
    factors["obv_change_5d"] = _obv(close, volume).pct_change(5)
    factors["vwap_deviation"] = (close - _vwap(high, low, close, volume)) / close
    factors["turnover_5d"] = volume.rolling(5).mean()  # proxy
    factors["dollar_vol_5d"] = (close * volume).rolling(5).mean()

    # ── Technical (10 factors) ────────────────────────────────────────
    factors["bb_width"]   = _bollinger_width(close)
    factors["bb_position"] = _bollinger_position(close)
    factors["ema_10_30"]  = _ema_ratio(close, 10, 30)
    factors["ema_20_60"]  = _ema_ratio(close, 20, 60)
    factors["ma_5_20"]    = _sma_ratio(close, 5, 20)
    factors["adx_14"]     = _adx(high, low, close, 14)
    factors["psar_diff"]  = _psar(high, low, close)
    factors["willr_14"]   = _williams_r(high, low, close, 14)
    factors["cci_14"]     = _cci(high, low, close, 14)
    factors["roc_10"]     = close.pct_change(10)

    # ── Value / Quality proxies (6 factors) ──────────────────────────
    factors["price_to_ma50"]  = close / close.rolling(50).mean() - 1
    factors["price_to_ma200"] = close / close.rolling(200).mean() - 1
    factors["sharpe_21d"] = returns.rolling(21).mean() / (returns.rolling(21).std() + 1e-8)
    factors["sharpe_63d"] = returns.rolling(63).mean() / (returns.rolling(63).std() + 1e-8)
    factors["sortino_63d"] = _sortino(returns, 63)
    factors["calmar_63d"]  = close.rolling(63).apply(
        lambda x: (x.iloc[-1] / x.iloc[0] - 1) / (_max_drawdown(x) + 0.01), raw=False)

    # Cross-sectional z-score: skip cols that are all-NA
    for col in factors.columns:
        zcol = factors[col]
        if not zcol.isna().all():
            factors[col + "_z"] = _zscore(zcol)

    return factors


def compute_forward_returns(close: pd.Series, horizon: int = 5) -> pd.Series:
    """Compute forward returns for ML label."""
    return close.shift(-horizon) / close - 1


# ════════════════ Indicator implementations ═══════════════════════════════════

def _rsi(close, period):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(span=period, adjust=False).mean()
    loss = (-delta).clip(lower=0).ewm(span=period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def _macd_hist(close, fast=12, slow=26, signal=9):
    ef = close.ewm(span=fast, adjust=False).mean()
    es = close.ewm(span=slow, adjust=False).mean()
    line = ef - es
    sig = line.ewm(span=signal, adjust=False).mean()
    return (line - sig) / close


def _trix(close, period):
    ema1 = close.ewm(span=period, adjust=False).mean()
    ema2 = ema1.ewm(span=period, adjust=False).mean()
    ema3 = ema2.ewm(span=period, adjust=False).mean()
    return ema3.pct_change()


def _kdj(high, low, close, n=9, m1=3, m2=3):
    low_n, high_n = low.rolling(n).min(), high.rolling(n).max()
    rsv = (close - low_n) / (high_n - low_n + 1e-8) * 100
    k = rsv.ewm(span=m1, adjust=False).mean()
    d = k.ewm(span=m2, adjust=False).mean()
    return k, d


def _atr(high, low, close, period):
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def _max_drawdown(close_series):
    peak = close_series.expanding().max()
    dd = (close_series - peak) / peak
    return abs(dd.min()) if len(dd) > 0 else 0.0


def _obv(close, volume):
    direction = np.sign(close.diff().fillna(0))
    return (direction * volume).cumsum()


def _vwap(high, low, close, volume):
    typical = (high + low + close) / 3
    return (typical * volume).cumsum() / volume.cumsum()


def _bollinger_width(close, period=20, std=2):
    ma = close.rolling(period).mean()
    std_dev = close.rolling(period).std()
    return (std_dev * std) / ma


def _bollinger_position(close, period=20, std=2):
    ma = close.rolling(period).mean()
    std_dev = close.rolling(period).std()
    return (close - ma) / (std_dev * std + 1e-8)


def _ema_ratio(close, fast, slow):
    ef = close.ewm(span=fast, adjust=False).mean()
    es = close.ewm(span=slow, adjust=False).mean()
    return ef / es - 1


def _sma_ratio(close, fast, slow):
    return close.rolling(fast).mean() / close.rolling(slow).mean() - 1


def _adx(high, low, close, period):
    tr = _atr(high, low, close, period)
    up = high.diff()
    down = -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    plus_di = 100 * plus_dm.ewm(span=period, adjust=False).mean() / (tr + 1e-8)
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / (tr + 1e-8)
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di + 1e-8)) * 100
    return dx.ewm(span=period, adjust=False).mean()


def _psar(high, low, close, af_step=0.02, af_max=0.2):
    psar = pd.Series(np.nan, index=close.index)
    trend = True  # True=uptrend
    ep = float(high.iloc[0])
    af = af_step
    psar.iloc[0] = float(low.iloc[0])
    for i in range(1, len(close)):
        prev = psar.iloc[i-1]
        psar.iloc[i] = prev + af * (ep - prev)
        if trend:
            if low.iloc[i] < psar.iloc[i]:
                trend = False
                psar.iloc[i] = ep
                ep = float(low.iloc[i])
                af = af_step
            else:
                if high.iloc[i] > ep:
                    ep = float(high.iloc[i])
                    af = min(af + af_step, af_max)
                psar.iloc[i] = min(psar.iloc[i], low.iloc[i-1]) if i > 1 else psar.iloc[i]
        else:
            if high.iloc[i] > psar.iloc[i]:
                trend = True
                psar.iloc[i] = ep
                ep = float(high.iloc[i])
                af = af_step
            else:
                if low.iloc[i] < ep:
                    ep = float(low.iloc[i])
                    af = min(af + af_step, af_max)
                psar.iloc[i] = max(psar.iloc[i], high.iloc[i-1]) if i > 1 else psar.iloc[i]
    return (close - psar) / close


def _williams_r(high, low, close, period):
    hh = high.rolling(period).max()
    ll = low.rolling(period).min()
    return (hh - close) / (hh - ll + 1e-8) * -100


def _cci(high, low, close, period):
    tp = (high + low + close) / 3
    ma = tp.rolling(period).mean()
    mad = tp.rolling(period).apply(lambda x: np.abs(x - x.mean()).mean())
    return (tp - ma) / (0.015 * mad + 1e-8)


def _sortino(returns, period):
    downside = returns.clip(upper=0)
    downside_std = downside.rolling(period).std()
    return returns.rolling(period).mean() / (downside_std + 1e-8)
