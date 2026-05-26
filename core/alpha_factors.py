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

from core.indicators import (
    rsi as _rsi_indicator,
    macd as _macd_indicator,
    atr as _atr_indicator,
    trix,
    kdj,
    obv,
    vwap,
    bollinger_bands,
    max_drawdown,
    adx,
    williams_r,
    cci,
    sortino_ratio,
)


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
    factors["rsi_14"]   = _rsi_indicator(close, 14)
    factors["rsi_28"]   = _rsi_indicator(close, 28)
    factors["macd_hist"] = _macd_indicator(close)["histogram"] / close
    factors["trix_14"]  = trix(close, 14)
    factors["kdj_k"]    = kdj(high, low, close)[0]
    factors["kdj_d"]    = kdj(high, low, close)[1]

    # ── Volatility (8 factors) ────────────────────────────────────────
    factors["vol_5d"]   = returns.rolling(5).std()
    factors["vol_21d"]  = returns.rolling(21).std()
    factors["vol_63d"]  = returns.rolling(63).std()
    factors["atr_14"]   = _atr_indicator(high, low, close, 14) / close
    factors["skew_21d"] = returns.rolling(21).skew()
    factors["kurt_21d"] = returns.rolling(21).kurt()
    factors["hl_ratio"] = (high - low) / close
    factors["max_dd_63d"] = close.rolling(63).apply(max_drawdown, raw=False)

    # ── Volume (6 factors) ────────────────────────────────────────────
    factors["vol_ratio_5d"]  = volume / volume.rolling(5).mean()
    factors["vol_ratio_21d"] = volume / volume.rolling(21).mean()
    factors["obv_change_5d"] = obv(close, volume).pct_change(5)
    factors["vwap_deviation"] = (close - vwap(high, low, close, volume)) / close
    factors["turnover_5d"] = volume.rolling(5).mean()  # proxy
    factors["dollar_vol_5d"] = (close * volume).rolling(5).mean()

    # ── Technical (10 factors) ────────────────────────────────────────
    factors["bb_width"]   = bollinger_bands(close)[3]
    factors["bb_position"] = bollinger_bands(close)[4]
    factors["ema_10_30"]  = _ema_ratio(close, 10, 30)
    factors["ema_20_60"]  = _ema_ratio(close, 20, 60)
    factors["ma_5_20"]    = _sma_ratio(close, 5, 20)
    factors["adx_14"]     = adx(high, low, close, 14)
    factors["psar_diff"]  = _psar(high, low, close)
    factors["willr_14"]   = williams_r(high, low, close, 14)
    factors["cci_14"]     = cci(high, low, close, 14)
    factors["roc_10"]     = close.pct_change(10)

    # ── Value / Quality proxies (6 factors) ──────────────────────────
    factors["price_to_ma50"]  = close / close.rolling(50).mean() - 1
    factors["price_to_ma200"] = close / close.rolling(200).mean() - 1
    factors["sharpe_21d"] = returns.rolling(21).mean() / (returns.rolling(21).std() + 1e-8)
    factors["sharpe_63d"] = returns.rolling(63).mean() / (returns.rolling(63).std() + 1e-8)
    factors["sortino_63d"] = sortino_ratio(returns, 63)
    factors["calmar_63d"]  = close.rolling(63).apply(
        lambda x: (x.iloc[-1] / x.iloc[0] - 1) / (max_drawdown(x) + 0.01), raw=False)

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
# Most indicators are imported from core.indicators.
# Only _psar (Parabolic SAR) and helpers _ema_ratio/_sma_ratio remain here
# as they are inline/lightweight enough not to warrant a separate module.


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


def _ema_ratio(close, fast, slow):
    ef = close.ewm(span=fast, adjust=False).mean()
    es = close.ewm(span=slow, adjust=False).mean()
    return ef / es - 1


def _sma_ratio(close, fast, slow):
    return close.rolling(fast).mean() / close.rolling(slow).mean() - 1
