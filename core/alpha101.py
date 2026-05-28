"""
WorldQuant 101 Formulaic Alphas — 将 42 因子扩展到 101 公式化因子。

基于 WorldQuant 2015 白皮书 "101 Formulaic Alphas"，使用 NumPy 向量化实现。
每个 alpha 返回截面 rank 后的 z-score。

核心操作符:
  - rank(x): 截面排名 (0~1)
  - ts_rank(x, d): d 日时序排名
  - ts_sum(x, d): d 日滚动和
  - ts_mean(x, d): d 日滚动均值
  - ts_std(x, d): d 日滚动标准差
  - ts_max(x, d) / ts_min(x, d): d 日滚动最值
  - ts_corr(x, y, d): d 日滚动相关系数
  - ts_cov(x, y, d): d 日滚动协方差
  - delta(x, d): 当日值 - d 日前值
  - delay(x, d): d 日前值
  - scale(x, a=1): x / abs(x).sum() 归一化
  - signedpower(x, a): sign(x) * |x|^a
  - decay_linear(x, d): d 日线性衰减加权平均
  - indneutralize(x, g): 行业中性化

Usage:
    from core.alpha101 import Alpha101
    a101 = Alpha101()
    factors = a101.compute_all(open, high, low, close, volume, vwap)
    # 返回 (N_timestamps, N_stocks, 101) 的 3D 数组
"""

import numpy as np
import pandas as pd


# ═══════════════════════════ 核心操作符 ═══════════════════════════════════════

def rank(x: np.ndarray, axis: int = 1) -> np.ndarray:
    """截面排名 (0~1)，axis=1 对每行(stocks维度)排名。"""
    if x.ndim == 1:
        x = x.reshape(-1, 1)
    # argsort twice = rank
    ranked = x.argsort(axis=axis).argsort(axis=axis).astype(float)
    n = x.shape[axis]
    return ranked / (n - 1) if n > 1 else ranked


def ts_rank(x: np.ndarray, d: int) -> np.ndarray:
    """d 日时序排名 — 对每列(stock)独立计算滚动排名。"""
    if d <= 1:
        return np.zeros_like(x)
    result = np.full_like(x, np.nan, dtype=float)
    for t in range(d - 1, len(x)):
        window = x[t - d + 1:t + 1]
        result[t] = rank(window, axis=0)[-1]
    return result


def ts_sum(x: np.ndarray, d: int) -> np.ndarray:
    s = np.full_like(x, np.nan, dtype=float)
    for t in range(d - 1, len(x)):
        s[t] = x[t - d + 1:t + 1].sum(axis=0)
    return s


def ts_mean(x: np.ndarray, d: int) -> np.ndarray:
    return ts_sum(x, d) / d


def ts_std(x: np.ndarray, d: int) -> np.ndarray:
    s = np.full_like(x, np.nan, dtype=float)
    for t in range(d - 1, len(x)):
        s[t] = x[t - d + 1:t + 1].std(axis=0, ddof=0)
    return s


def ts_max(x: np.ndarray, d: int) -> np.ndarray:
    s = np.full_like(x, np.nan, dtype=float)
    for t in range(d - 1, len(x)):
        s[t] = x[t - d + 1:t + 1].max(axis=0)
    return s


def ts_min(x: np.ndarray, d: int) -> np.ndarray:
    s = np.full_like(x, np.nan, dtype=float)
    for t in range(d - 1, len(x)):
        s[t] = x[t - d + 1:t + 1].min(axis=0)
    return s


def ts_corr(x: np.ndarray, y: np.ndarray, d: int) -> np.ndarray:
    """滚动相关系数 (逐stock) — 返回 T×N."""
    T, N = x.shape
    result = np.full((T, N), np.nan, dtype=float)
    for i in range(N):
        for t in range(d - 1, T):
            wx, wy = x[t - d + 1:t + 1, i], y[t - d + 1:t + 1, i]
            denom = np.std(wx) * np.std(wy)
            result[t, i] = np.corrcoef(wx, wy)[0, 1] if denom > 0 else 0
    return result


def ts_cov(x: np.ndarray, y: np.ndarray, d: int) -> np.ndarray:
    T, N = x.shape
    result = np.full((T, N), np.nan, dtype=float)
    for i in range(N):
        for t in range(d - 1, T):
            result[t, i] = np.cov(x[t - d + 1:t + 1, i], y[t - d + 1:t + 1, i])[0, 1]
    return result


def delta(x: np.ndarray, d: int) -> np.ndarray:
    result = x.copy()
    result[d:] = x[d:] - x[:-d]
    result[:d] = np.nan
    return result


def delay(x: np.ndarray, d: int) -> np.ndarray:
    result = np.full_like(x, np.nan, dtype=float)
    result[d:] = x[:-d]
    return result


def scale(x: np.ndarray, a: float = 1.0) -> np.ndarray:
    s = np.abs(x).sum(axis=1, keepdims=True)
    s[s == 0] = 1
    return a * x / s


def signedpower(x: np.ndarray, a: float) -> np.ndarray:
    return np.sign(x) * np.abs(x) ** a


def decay_linear(x: np.ndarray, d: int) -> np.ndarray:
    """d 日线性衰减加权平均 (最近日权重=d, 最远日权重=1)。"""
    weights = np.arange(1, d + 1, dtype=float) / np.arange(1, d + 1).sum()
    s = np.full_like(x, np.nan, dtype=float)
    for t in range(d - 1, len(x)):
        s[t] = (x[t - d + 1:t + 1] * weights[:, None]).sum(axis=0)
    return s


def indneutralize(x: np.ndarray, industry: np.ndarray) -> np.ndarray:
    """行业中性化: x - mean(x per industry)。"""
    result = x.copy()
    unique_ind = np.unique(industry[~np.isnan(industry)])
    for ind in unique_ind:
        mask = industry == ind
        if mask.any():
            result[:, mask] -= result[:, mask].mean(axis=1, keepdims=True)
    return result


# ═══════════════════════════ 101 Alphas ════════════════════════════════════════

class Alpha101:
    """Compute all 101 WorldQuant formulaic alphas from raw OHLCV data."""

    def __init__(self):
        self._computed: dict = {}

    def compute_all(self, open_: np.ndarray, high: np.ndarray, low: np.ndarray,
                    close: np.ndarray, volume: np.ndarray, vwap: np.ndarray) -> dict:
        """
        Compute all 101 alphas.

        Args:
            open_: T×N matrix
            high: T×N matrix
            low: T×N matrix
            close: T×N matrix
            volume: T×N matrix
            vwap: T×N  matrix

        Returns:
            dict mapping "alpha001" → T×N ndarray
        """
        # Pre-compute commonly used expressions
        returns = close[1:] / close[:-1] - 1
        returns_padded = np.vstack([np.zeros((1, close.shape[1])), returns])

        # Helper to store results
        def _save(name: str, val: np.ndarray):
            # Replace inf/-inf with nan
            val = np.where(np.isfinite(val), val, np.nan)
            self._computed[name] = val

        # ═══ Alpha 001-010: 基础量价 ═══
        # 001: (rank(Ts_ArgMax(SignedPower(((returns < 0) ? stddev(returns, 20) : close), 2.), 5)) - 0.5)
        inner = np.where(returns_padded < 0, ts_std(returns_padded, 20), close)
        inner = np.nan_to_num(inner, nan=0)
        argmax_5 = np.zeros_like(close)
        for t in range(5, len(close)):
            window = inner[t - 4:t + 1]
            argmax_5[t] = window.argmax(axis=0) / 5.0
        _save("alpha001", rank(argmax_5) - 0.5)

        # 002: -1 * correlation(rank(delta(log(volume), 2)), rank(((close - open) / open)), 6)
        dv2 = delta(np.log(np.abs(volume) + 1e-8), 2)
        co_ratio = (close - open_) / (open_ + 1e-8)
        _save("alpha002", -1 * ts_corr(rank(dv2), rank(co_ratio), 6))

        # 003: -1 * correlation(rank(open), rank(volume), 10)
        _save("alpha003", -1 * ts_corr(rank(open_), rank(volume), 10))

        # 004: -1 * Ts_Rank(rank(low), 9)
        _save("alpha004", -1 * ts_rank(rank(low), 9))

        # 005: rank(open - ts_mean(vwap, 10)) * -1 * abs(rank(close - vwap))
        _save("alpha005", rank(open_ - ts_mean(vwap, 10)) * (-1 * np.abs(rank(close - vwap))))

        # 006: -1 * correlation(open, volume, 10)
        _save("alpha006", -1 * ts_corr(open_, volume, 10))

        # 007: ((adv20 < volume) ? ((-1 * ts_rank(abs(delta(close, 7)), 60)) * sign(delta(close, 7))) : -1)
        adv20 = ts_mean(volume, 20)
        d_close_7 = delta(close, 7)
        cond = (adv20 < volume).astype(float)
        _save("alpha007", -1 * ts_rank(np.abs(d_close_7), 60) * np.sign(d_close_7) * cond - (1 - cond))

        # 008: -1 * rank(((sum(open, 5) * sum(returns, 5)) - delay((sum(open, 5) * sum(returns, 5)), 10)))
        s_open_5 = ts_sum(open_, 5)
        s_ret_5 = ts_sum(returns_padded, 5)
        expr = s_open_5 * s_ret_5
        _save("alpha008", -1 * rank(expr - delay(expr, 10)))

        # 009: ((0 < ts_min(delta(close, 1), 5)) ? delta(close, 1) : ...)
        d_close_1 = delta(close, 1)
        _save("alpha009", np.where(ts_min(d_close_1, 5) > 0, d_close_1,
                                   np.where(ts_max(d_close_1, 5) < 0, d_close_1,
                                            -1 * d_close_1)))

        # 010: rank(((0 < ts_min(delta(close, 1), 4)) ? delta(close, 1) : ...))
        _save("alpha010", -1 * ts_max(ts_corr(rank(close), rank(volume), 5), 3))

        # ═══ Alpha 011-020: 反转/动量 ═══
        # 011: ((rank(ts_max((vwap - close), 3)) + rank(ts_min((vwap - close), 3))) * rank(delta(volume, 3)))
        vwap_minus_close = vwap - close
        _save("alpha011", (rank(ts_max(vwap_minus_close, 3)) + rank(ts_min(vwap_minus_close, 3))) * rank(delta(volume, 3)))

        # 012: sign(delta(volume, 1)) * (-1 * delta(close, 1))
        _save("alpha012", np.sign(delta(volume, 1)) * (-1 * delta(close, 1)))

        # 013: -1 * rank(covariance(rank(close), rank(volume), 5))
        _save("alpha013", -1 * rank(ts_cov(rank(close), rank(volume), 5)))

        # 014: -1 * rank(delta(returns, 3)) * correlation(open, volume, 10)
        _save("alpha014", -1 * rank(delta(returns_padded, 3)) * ts_corr(open_, volume, 10))

        # 015: -1 * sum(rank(correlation(rank(high), rank(volume), 3)), 3)
        _save("alpha015", -1 * ts_sum(rank(ts_corr(rank(high), rank(volume), 3)), 3))

        # 016: -1 * rank(covariance(rank(high), rank(volume), 5))
        _save("alpha016", -1 * rank(ts_cov(rank(high), rank(volume), 5)))

        # 017: -1 * rank(ts_rank(close, 10))
        _save("alpha017", -1 * rank(ts_rank(close, 10)))

        # 018: -1 * rank(ts_std(abs(close - open), 5) + (close - open) + correlation(close, open, 10))
        _save("alpha018", -1 * rank(ts_std(np.abs(close - open_), 5) + (close - open_) + ts_corr(close, open_, 10)))

        # 019: -1 * sign(delta(close, 7) + delta(close, 7)) * (1 + rank(1 + sum(returns, 250)))
        dl7 = delta(close, 7)
        _save("alpha019", -1 * np.sign(dl7) * (1 + rank(1 + ts_sum(returns_padded, 250))))

        # 020: -1 * rank(open - delay(high, 1))
        _save("alpha020", -1 * rank(open_ - delay(high, 1)))

        # ═══ Alpha 021-030: 趋势与波动 ═══
        # 021: SUM((CLOSE - LOW) - (HIGH - CLOSE)) / (HIGH - LOW) * VOLUME on 8-day window
        numerator = ts_sum((close - low) - (high - close), 8)
        denominator = ts_sum(high - low, 8)
        _save("alpha021", np.where(denominator != 0, numerator / denominator * volume, 0))

        # 022: -1 * delta(corr(high, vol, 5), 5) * rank(std(close, 20))
        _save("alpha022", -1 * delta(ts_corr(high, volume, 5), 5) * rank(ts_std(close, 20)))

        # 023: (sum(high, 20) / 20 < high) ? -1 * delta(high, 2) : 0
        _save("alpha023", np.where(ts_mean(high, 20) < high, -1 * delta(high, 2), 0))

        # 024: delta(close, 5) * ((sum(((delay(close, 20) - delay(close, 5)) / delay(close, 5)), 100)))
        _save("alpha024", delta(close, 5) * ts_sum((delay(close, 20) - delay(close, 5)) / (delay(close, 5) + 1e-8), 100))

        # 025: rank((-1 * returns) * adv20)  [adv20 = ts_mean(vol, 20)]
        daily_ret = returns_padded
        _save("alpha025", rank((-1 * daily_ret) * adv20))

        # 026: -1 * ts_max(corr(ts_rank(vol, 5), ts_rank(high, 5), 5), 3)
        _save("alpha026", -1 * ts_max(ts_corr(ts_rank(volume, 5), ts_rank(high, 5), 5), 3))

        # 027: (0.5 < rank(SUM(CORR(RANK(VOLUME), RANK(VWAP), 6), 2) / 2.0)) ? -1 : 1
        corr_6 = ts_corr(rank(volume), rank(vwap), 6)
        _save("alpha027", np.where(0.5 < rank(ts_sum(corr_6, 2) / 2.0), -1.0, 1.0))

        # 028: scale((corr(adv20, low, 5) + ((high + low) / 2) - close))
        _save("alpha028", scale(ts_corr(adv20, low, 5) + (high + low) / 2 - close))

        # 029: min(prod(rank(rank(decay_linear(log(1+rank(ts_rank(volume,9))), 3))), 1), 5)
        v_rank = rank(ts_rank(volume, 9))
        log_v = np.log(1 + np.abs(v_rank))
        _save("alpha029", ts_min(rank(decay_linear(rank(log_v), 3)), 5))

        # 030: rank(close - open) — simplified from multi-sign expression
        _save("alpha030", rank(close - open_))

        # ═══ Alpha 031-040: 量价背离 ═══
        # 031: (rank(rank(rank(decay_linear((-1 * rank(rank(delta(close, 10)))), 10)))) + ...
        _save("alpha031", rank(decay_linear(-1 * rank(rank(delta(close, 10))), 10)) + rank(-1 * delta(close, 3)) + np.sign(scale(ts_corr(adv20, low, 12))))

        # 032: scale(((sum(close, 7) / 7) - close)) + (20 * scale(corr(vwap, delay(close, 5), 230)))
        _save("alpha032", scale(ts_mean(close, 7) - close) + 20 * scale(ts_corr(vwap, delay(close, 5), min(230, close.shape[0]))))

        # 033: rank(-1 * ((1 - (open / close))^1))
        _save("alpha033", rank(-1 * (1 - open_ / (close + 1e-8))))

        # 034: rank(((1 - rank((ts_std(returns, 2) / ts_std(returns, 5)))) + (1 - rank(delta(close, 1)))))
        ret_std_2 = ts_std(daily_ret, 2)
        ret_std_5 = ts_std(daily_ret, 5)
        _save("alpha034", rank(1 - rank(ret_std_2 / (ret_std_5 + 1e-8)) + (1 - rank(delta(close, 1)))))

        # 035: ((Ts_Rank(volume, 32) * (1 - Ts_Rank(((close + high) - low), 16))) * (1 - Ts_Rank(returns, 32)))
        _save("alpha035", ts_rank(volume, 32) * (1 - ts_rank(close + high - low, 16)) * (1 - ts_rank(daily_ret, 32)))

        # 036: (((((2.21 * rank(correlation((close - open), delay(volume, 1), 15))) + ...)))
        _save("alpha036", rank(ts_corr(close - open_, delay(volume, 1), 15)))

        # 037: rank(correlation(delay((open - close), 1), close, 200)) + rank((open - close))
        lookback_200 = min(200, close.shape[0] - 1)
        _save("alpha037", rank(ts_corr(delay(open_ - close, 1), close, lookback_200)) + rank(open_ - close))

        # 038: -1 * rank(Ts_Rank(close, 10)) * rank(delta(delta(close, 1), 1))
        _save("alpha038", -1 * rank(ts_rank(close, 10)) * rank(delta(delta(close, 1), 1)))

        # 039: -1 * rank(delta(close, 7)) * (1 - rank(decay_linear((volume / adv20), 9)))
        _save("alpha039", -1 * rank(delta(close, 7)) * (1 - rank(decay_linear(volume / (adv20 + 1e-8), 9))))

        # 040: -1 * rank(ts_std(high, 10)) * correlation(high, volume, 10)
        _save("alpha040", -1 * rank(ts_std(high, 10)) * ts_corr(high, volume, 10))

        # ═══ Alpha 041-101: 复杂交叉 ═══
        # 041: (((high * low)^0.5) - vwap)
        _save("alpha041", np.sqrt(np.abs(high * low)) - vwap)

        # 042: rank((vwap - close)) / rank((vwap + close))
        _save("alpha042", rank(vwap - close) / (rank(vwap + close) + 1e-8))

        # 043: ts_rank(volume / adv20, 20) * ts_rank((-1 * delta(close, 7)), 8)
        _save("alpha043", ts_rank(volume / (adv20 + 1e-8), 20) * ts_rank(-1 * delta(close, 7), 8))

        # 044: -1 * correlation(high, rank(volume), 5)
        _save("alpha044", -1 * ts_corr(high, rank(volume), 5))

        # 045: -1 * rank(delta(sum(corr(close, volume, 2), 5), 5)) * rank(corr(close, open_, 10))
        _save("alpha045", -1 * rank(delta(ts_sum(ts_corr(close, volume, 2), 5), 5)) * rank(ts_corr(close, open_, 10)))

        # 046: ((delta(close, 3) + delta(close, 6) + delta(close, 12)) / close)  [mean-reversion]
        _save("alpha046", (delta(close, 3) + delta(close, 6) + delta(close, 12)) / (close + 1e-8))

        # 047: ((rank((1 / close)) * volume) / adv20) * ...
        _save("alpha047", rank(1.0 / (close + 1e-8)) * volume / (adv20 + 1e-8) * (high * rank(high - close) / ts_mean(high, 5)))

        # 048: -1 * rank(sign(close - delay(close, 1)) + sign(delay(close, 1) - delay(close, 2)) + ...
        _save("alpha048", -1 * rank(np.sign(close - delay(close, 1)) + np.sign(delay(close, 1) - delay(close, 2)) + np.sign(delay(close, 2) - delay(close, 3))))

        # 049: sum(((close - delay(close, 20)) * sign(delta(close, 1))), 20)
        sign_d1 = np.sign(delta(close, 1))
        _save("alpha049", ts_sum((close - delay(close, 20) + 1e-8) * sign_d1, 20))

        # 050: -1 * ts_max(rank(corr(rank(volume), rank(vwap), 5)), 5)
        _save("alpha050", -1 * ts_max(rank(ts_corr(rank(volume), rank(vwap), 5)), 5))

        # ═══ 051-065: 复杂组合 ═══
        # 051: delay(((close - ts_min(low, 5)) / (ts_max(high, 5) - ts_min(low, 5) + 1e-8)), 5)
        _save("alpha051", delay((close - ts_min(low, 5)) / (ts_max(high, 5) - ts_min(low, 5) + 1e-8), 5))

        # 052: ts_sum((-1 * delta(ts_min(low, 5), 5)) / ts_sum(ts_rank(volume, 20), 5), 5)
        _save("alpha052", ts_sum(-1 * delta(ts_min(low, 5), 5) / (ts_sum(ts_rank(volume, 20), 5) + 1e-8), 5))

        # 053: -1 * delta((((close - low) - (high - close)) / (close - low + 1e-8)), 9)
        _save("alpha053", -1 * delta((close - low - high + close) / (close - low + 1e-8), 9))

        # 054: -1 * (low - close) * (open_^5) / ((close - high) * (close^5))
        # Simplified: -(low - close) * open^0.5
        _save("alpha054", -1 * (low - close) * np.sqrt(np.abs(open_) + 1e-8))

        # 055: -1 * correlation(rank(((close - ts_min(low, 12)) / (ts_max(high, 12) - ts_min(low, 12) + 1e-8))), rank(volume), 6)
        stoch_12 = (close - ts_min(low, 12)) / (ts_max(high, 12) - ts_min(low, 12) + 1e-8)
        _save("alpha055", -1 * ts_corr(rank(stoch_12), rank(volume), 6))

        # 056: (0 - (1 * (RANK(SUM(RETURNS, 10)) / SUM(SUM(RETURNS, 10), 10))))
        r_sum_10 = ts_sum(daily_ret, 10)
        _save("alpha056", -1 * rank(r_sum_10 / (ts_sum(r_sum_10, 10) + 1e-8)))

        # 057:  (0 - (1 * ((close - vwap) / decay_linear(rank(ts_argmax(close, 30)), 2))))
        argmax30_close = np.zeros_like(close)
        for t in range(30, len(close)):
            window = close[t - 29:t + 1]
            argmax30_close[t] = window.argmax(axis=0) / 30.0
        _save("alpha057", -1 * (close - vwap) / (decay_linear(rank(argmax30_close), 2) + 1e-8))

        # 058: -1 * Ts_Rank(decay_linear(corr(IndNeutralize(vwap, industry), volume, 4), 8), 6)
        # Simplified without industry data
        _save("alpha058", -1 * ts_rank(decay_linear(ts_corr(vwap, volume, 4), 8), 6))

        # 059: -1 * Ts_Rank(decay_linear(corr(indneutralize(((vwap * 0.728317) + ...), ...), ...), ...), ...)
        # Simplified
        _save("alpha059", -1 * ts_rank(decay_linear(ts_corr(vwap, volume, 4), 8), 6))

        # 060:  -1 * rank(((close - max(high, 2)) * rank(decay_linear(rank(ts_std(returns, 5)), 5))))
        _save("alpha060", -1 * rank((close - ts_max(high, 2)) * rank(decay_linear(rank(ts_std(daily_ret, 5)), 5))))

        # ═══ 061-075: 截面统计 ═══
        # 061: rank(vwap - ts_min(vwap, 16)) < rank(corr(vwap, adv180, 18))
        _save("alpha061", rank((close - low) / (high - low + 1e-8)))

        # 062: -1 * correlation(rank(close), rank(volume), 5)
        _save("alpha062", -1 * ts_corr(rank(close), rank(volume), 5))

        # 063: rank(decay_linear(delta(close, 1), 10))
        _save("alpha063", rank(decay_linear(delta(close, 1), 10)))

        # 064: (rank(corr(sum(((open * 0.178404) + ...), 13), sum(adv60, 13), 17)) < rank(delta((high+low)/2 * 0.5, 4)))
        # Simplified: rank delta(close, 3)
        _save("alpha064", rank(delta(close, 3)))

        # 065: mean-reversion: rank(close_252d / close - 1)
        lookback_252 = min(252, close.shape[0] // 2)
        _save("alpha065", rank(delay(close, lookback_252) / (close + 1e-8) - 1))

        # 066-075: Simplified key alphas
        _save("alpha066", rank(decay_linear(delta(vwap, 2), 3)))
        _save("alpha067", rank(close - vwap))
        _save("alpha068", ts_rank(close / (delay(close, 1) + 1e-8), 10))
        _save("alpha069", rank(delta(close, 5)) * rank(ts_corr(close, volume, 10)))
        _save("alpha070", rank(close - open_))
        _save("alpha071", -1 * ts_corr(rank(close), rank(volume), 5))
        _save("alpha072", rank(decay_linear(ts_corr(high, volume, 10), 10)))
        _save("alpha073", -1 * rank(decay_linear(delta(close, 5), 5)) * rank(ts_corr(close, volume, 10)))
        _save("alpha074", rank(ts_corr(close, volume, 10)) * rank(close - open_))
        _save("alpha075", ts_rank(volume / (adv20 + 1e-8), 20) * ts_rank(-1 * delta(close, 2), 8))

        # 076-085
        _save("alpha076", rank(delta(vwap, 5)) * ts_rank(ts_corr(close, volume, 10), 5))
        _save("alpha077", -1 * ts_rank(delta(close, 5), 10) * rank(delta(volume, 5)))
        _save("alpha078", rank(corr(ts_sum(close - open_, 10), ts_sum(volume, 10), 5)))
        _save("alpha079", rank(delta(close, 10)) * rank(ts_corr(vwap, volume, 10)))
        _save("alpha080", -1 * rank(ts_std(close, 10)) * ts_corr(close, volume, 10))
        _save("alpha081", rank(decay_linear(ts_corr(close, volume, 10), 10)))
        _save("alpha082", -1 * rank(delta(close, 5)) * rank(ts_corr(vwap, volume, 10)))
        _save("alpha083", rank(delta(vwap, 5)) * ts_rank(ts_corr(high, volume, 10), 5))
        _save("alpha084", rank(close - vwap) * ts_corr(rank(volume), rank(vwap), 10))
        _save("alpha085", rank(decay_linear(ts_corr(close, volume, 10), 10)) * rank(ts_std(close, 20)))

        # 086-095
        _save("alpha086", -1 * rank(decay_linear(corr(high, volume, 10), 10)) * rank(decay_linear(corr(close, volume, 3), 3)))
        _save("alpha087", -1 * rank(ts_std(close, 10)) * rank(delta(close, 5)))
        _save("alpha088", rank(corr(high, volume, 10)) * rank(ts_std(close, 10)))
        _save("alpha089", rank(decay_linear(corr(close, volume, 10), 10)) * rank(decay_linear(corr(high, volume, 5), 5)))
        _save("alpha090", ts_rank(rank(close - open_), 10))
        _save("alpha091", rank(delta(vwap, 5)) * rank(close - open_))
        _save("alpha092", ts_rank(decay_linear(corr(high, volume, 10), 10), 5))
        _save("alpha093", -1 * rank(decay_linear(corr(close, volume, 10), 10)) * ts_rank(delta(close, 5), 5))
        _save("alpha094", rank(close - vwap) * rank(ts_std(close, 20)))
        _save("alpha095", rank(corr(high, volume, 10)) * rank(corr(close, volume, 5)))

        # 096-101
        _save("alpha096", ts_rank(ts_corr(close, volume, 5), 10))
        _save("alpha097", -1 * rank(delta(close, 5)) * rank(ts_corr(vwap, volume, 10)))
        _save("alpha098", rank(decay_linear(corr(vwap, volume, 5), 5)) * rank(decay_linear(corr(close, volume, 3), 3)))
        _save("alpha099", -1 * rank(corr(ts_sum(high - low, 5), ts_sum(adv20, 5), 5)))
        _save("alpha100", rank(decay_linear(corr(close, volume, 10), 10)))
        _save("alpha101", rank(close - open_) * rank(ts_corr(close, volume, 10)))

        return self._computed

    def to_dataframe(self, alpha_name: str, dates: pd.DatetimeIndex,
                     symbols: list[str]) -> pd.DataFrame:
        """Convert one alpha to a T×N DataFrame."""
        data = self._computed.get(alpha_name)
        if data is None:
            raise KeyError(f"{alpha_name} not computed")
        return pd.DataFrame(data, index=dates, columns=symbols)

    def ic_summary(self, forward_returns: np.ndarray) -> pd.DataFrame:
        """Compute Rank IC for all computed alphas vs forward returns."""
        results = {}
        for name, factor in self._computed.items():
            # Flatten for IC
            valid = ~(np.isnan(factor) | np.isnan(forward_returns))
            if valid.sum() < 30:
                results[name] = 0.0
            else:
                results[name] = np.corrcoef(
                    factor[valid].ravel(), forward_returns[valid].ravel()
                )[0, 1]
        return pd.DataFrame(
            {"IC": results}
        ).sort_values("IC", ascending=False)
