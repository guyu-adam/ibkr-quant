"""
策略核心：动量 + 均值回归 混合信号

逻辑：
  1. 动量层（趋势过滤）：EMA_fast > EMA_slow → 偏多头环境，反之偏空头
  2. 均值回归层（入场触发）：RSI 超买超卖给出具体入场点
  3. ATR 止盈止损：入场后动态设置
  4. 两层信号均同向时才开仓，避免在强趋势中逆势

信号枚举：
  +1 做多（RSI 超卖 + 动量偏多）
  -1 做空（RSI 超买 + 动量偏空）
   0 无信号
"""

import numpy as np
import pandas as pd
from config.settings import RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT, MOM_FAST, MOM_SLOW, ATR_PERIOD


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    avg_g = gain.ewm(span=period, adjust=False).mean()
    avg_l = loss.ewm(span=period, adjust=False).mean()
    rs = avg_g / avg_l.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"]  - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["rsi"]      = rsi(df["close"], RSI_PERIOD)
    df["ema_fast"] = ema(df["close"], MOM_FAST)
    df["ema_slow"] = ema(df["close"], MOM_SLOW)
    df["atr"]      = atr(df, ATR_PERIOD)
    df["momentum"] = df["ema_fast"] - df["ema_slow"]  # > 0 多头, < 0 空头
    return df


def generate_signal(df: pd.DataFrame) -> dict:
    """
    传入含指标的 DataFrame，返回最新信号字典：
    {
        "signal":     +1 / -1 / 0,
        "price":      最新收盘价,
        "atr":        当前 ATR,
        "stop_long":  做多止损价,
        "stop_short": 做空止损价,
        "reason":     信号描述
    }
    """
    row = df.iloc[-1]
    signal = 0
    reason = "no signal"

    bullish_trend = row["momentum"] > 0
    bearish_trend = row["momentum"] < 0

    # 做多：RSI 超卖 + 动量偏多
    if row["rsi"] < RSI_OVERSOLD and bullish_trend:
        signal = 1
        reason = f"RSI={row['rsi']:.1f}<{RSI_OVERSOLD}  EMA_fast>EMA_slow"

    # 做空：RSI 超买 + 动量偏空
    elif row["rsi"] > RSI_OVERBOUGHT and bearish_trend:
        signal = -1
        reason = f"RSI={row['rsi']:.1f}>{RSI_OVERBOUGHT}  EMA_fast<EMA_slow"

    return {
        "signal":      signal,
        "price":       row["close"],
        "atr":         row["atr"],
        "stop_long":   row["close"] - row["atr"] * 2.0,
        "stop_short":  row["close"] + row["atr"] * 2.0,
        "reason":      reason,
    }
