"""
Alpha 因子库 — 多维度标准化因子计算

因子分类（参考 qlib Alpha158 + WorldQuant 101）:
  - 动量类: 1/3/6/12月收益率、RSI、MACD
  - 波动类: 历史波动率、ATR比率、偏度、峰度
  - 换手类: 换手率变化、成交量比率
  - 质量类: 毛利率、ROE（需基本面数据，暂用代理）
  - 价值类: PE/PB代理（价格/均线偏离）
  - 技术类: 布林带、EMA交叉、OBV

每个因子输出时进行截面标准化（z-score cross-sectional）。
"""

import numpy as np
import pandas as pd
from typing import Optional


def _zscore(series: pd.Series) -> pd.Series:
    """截面标准化（去均值/标准差）"""
    mu, std = series.mean(), series.std()
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=series.index)
    return (series - mu) / std


def compute_factors(df: pd.DataFrame) -> pd.DataFrame:
    """
    输入: df with columns [open, high, low, close, volume]
    输出: DataFrame of standardized alpha factors
    """
    close  = df['close'].astype(float)
    high   = df['high'].astype(float)
    low    = df['low'].astype(float)
    volume = df['volume'].astype(float)
    returns = close.pct_change()

    factors = pd.DataFrame(index=df.index)

    # ═══════════════════ 动量类 ═══════════════════
    for p in [5, 10, 21, 42, 63]:  # 1w/2w/1m/2m/3m
        factors[f'mom_{p}d'] = close.pct_change(p)

    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    factors['rsi_14'] = 100.0 - 100.0 / (1.0 + rs)

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    factors['macd'] = ema12 - ema26
    factors['macd_signal'] = factors['macd'].ewm(span=9, adjust=False).mean()
    factors['macd_hist'] = factors['macd'] - factors['macd_signal']

    # ═══════════════════ 波动类 ═══════════════════
    factors['vol_5d']  = returns.rolling(5).std()
    factors['vol_21d'] = returns.rolling(21).std()
    factors['vol_42d'] = returns.rolling(42).std()
    factors['vol_ratio'] = factors['vol_5d'] / factors['vol_21d'].replace(0, np.nan)  # 短期/长期波动比

    # ATR
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    factors['atr_14'] = tr.rolling(14).mean() / close  # ATR 比率

    # 偏度/峰度
    factors['skew_21d']  = returns.rolling(21).skew()
    factors['kurt_21d']  = returns.rolling(21).kurt()

    # Max drawdown (21d)
    peak_21 = close.rolling(21).max()
    factors['mdd_21d'] = (close - peak_21) / peak_21

    # ═══════════════════ 换手/流动性类 ═══════════════════
    factors['vol_5d_ma']  = volume.rolling(5).mean()
    factors['vol_21d_ma'] = volume.rolling(21).mean()
    factors['vol_ratio_v'] = factors['vol_5d_ma'] / factors['vol_21d_ma'].replace(0, np.nan)
    factors['vol_chg'] = volume.pct_change(5)

    # Amihud 非流动性（收益率绝对值/成交量）
    factors['illiquidity'] = returns.abs() / (volume.replace(0, np.nan) * close)

    # ═══════════════════ 价值代理类 ═══════════════════
    # 价格/均线偏离（代理 PE/PB 估值偏离）
    for p in [21, 63]:
        ma = close.rolling(p).mean()
        factors[f'price_ma{p}_dev'] = (close - ma) / ma

    # ═══════════════════ 技术类 ═══════════════════
    # 布林带
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    factors['bb_width'] = (bb_std * 2) / bb_mid
    factors['bb_position'] = (close - bb_mid) / (bb_std * 2)

    # EMA 交叉信号
    ema10 = close.ewm(span=10, adjust=False).mean()
    ema30 = close.ewm(span=30, adjust=False).mean()
    factors['ema_cross'] = (ema10 - ema30) / close

    # OBV 变化率
    obv = (np.sign(close.diff()) * volume).cumsum()
    factors['obv_chg'] = obv.pct_change(5)

    # 威廉 %R
    high_14, low_14 = high.rolling(14).max(), low.rolling(14).min()
    factors['williams_r'] = (high_14 - close) / (high_14 - low_14).replace(0, np.nan) * -100

    # ═══════════════════ 截面标准化 ═══════════════════
    for col in factors.columns:
        factors[col] = factors[col].astype(float)

    return factors


def compute_forward_returns(close: pd.Series, horizon: int = 5) -> pd.Series:
    """
    计算未来 N 日收益率（预测目标）
    horizon=5 表示预测未来 5 日收益
    """
    future = close.shift(-horizon)
    return (future - close) / close


def prepare_ml_data(df: pd.DataFrame, horizon: int = 5) -> tuple:
    """
    准备机器学习数据

    Returns:
        X: 因子矩阵 (n_samples, n_factors)
        y: 未来收益标签
        dates: 日期索引
    """
    factors = compute_factors(df)
    forward = compute_forward_returns(df['close'], horizon)

    # 对齐并去 NaN
    common_idx = factors.dropna().index.intersection(forward.dropna().index)
    X = factors.loc[common_idx].fillna(0.0)
    y = forward.loc[common_idx]

    return X, y, common_idx
