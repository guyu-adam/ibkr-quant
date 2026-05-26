"""
杠杆策略 v2 — 协整配对交易 + 杠杆ETF趋势。

Enhancements (P1):
  - Cointegration-based pair selection (Engle-Granger test)
  - z-score entry/exit with configurable thresholds
  - Half-life estimation for mean-reversion speed
"""

import logging
import numpy as np
import pandas as pd
from core.strategy_base import BaseStrategy
from config.settings import (
    PAIRS_Z_ENTRY, PAIRS_Z_EXIT, PAIRS_HALFLIFE_MIN, PAIRS_HALFLIFE_MAX, PAIRS_CORR_MIN,
)

log = logging.getLogger(__name__)


def estimate_half_life(spread: pd.Series) -> float:
    """Estimate half-life of mean reversion via OLS on lagged spread."""
    spread_lag = spread.shift(1).dropna()
    spread_diff = spread.diff().dropna()
    # Align
    common_idx = spread_lag.index.intersection(spread_diff.index)
    if len(common_idx) < 20:
        return 999
    y = spread_diff.loc[common_idx].values
    x = spread_lag.loc[common_idx].values
    # OLS: delta_spread = alpha + beta * spread_lag + eps
    # half-life = -ln(2) / beta
    X = np.column_stack([np.ones(len(x)), x])
    try:
        beta = np.linalg.lstsq(X, y, rcond=None)[0][1]
        if beta >= 0:
            return 999
        hl = -np.log(2) / beta
        return float(hl)
    except np.linalg.LinAlgError:
        return 999


def find_cointegrated_pairs(prices: pd.DataFrame, corr_min=PAIRS_CORR_MIN,
                            hl_min=PAIRS_HALFLIFE_MIN, hl_max=PAIRS_HALFLIFE_MAX) -> list[tuple]:
    """Screen all pairs for cointegration, return valid pairs with hedge ratios."""
    from statsmodels.tsa.stattools import coint
    symbols = prices.columns
    pairs = []
    for i, a in enumerate(symbols):
        for b in symbols[i+1:]:
            pa, pb = prices[a].dropna(), prices[b].dropna()
            common = pa.index.intersection(pb.index)
            if len(common) < 120:
                continue
            pa, pb = pa[common], pb[common]
            corr = pa.corr(pb)
            if abs(corr) < corr_min:
                continue
            try:
                score, pvalue, _ = coint(pa, pb)
                if pvalue < 0.05:
                    # hedge ratio: OLS on prices
                    X = np.column_stack([np.ones(len(pa)), pa.values])
                    hedge = np.linalg.lstsq(X, pb.values, rcond=None)[0][1]
                    spread = pb - hedge * pa
                    hl = estimate_half_life(spread)
                    if hl_min <= hl <= hl_max:
                        pairs.append((a, b, hedge, hl, corr, pvalue))
            except Exception:
                continue
    return sorted(pairs, key=lambda x: x[5])  # lowest p-value first


class CointegrationPairStrategy(BaseStrategy):
    """
    协整配对策略 — Engle-Granger 检验 + z-score 进出场。

    Long the loser, short the winner. Market-neutral when hedged.
    """

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.z_entry  = cfg.get("z_entry", PAIRS_Z_ENTRY)
        self.z_exit   = cfg.get("z_exit", PAIRS_Z_EXIT)
        self.corr_min = cfg.get("corr_min", PAIRS_CORR_MIN)
        self.hl_min   = cfg.get("halflife_min", PAIRS_HALFLIFE_MIN)
        self.hl_max   = cfg.get("halflife_max", PAIRS_HALFLIFE_MAX)
        self._pairs: list[dict] = []       # [{a, b, hedge, spread_hist}]
        self._active: dict[tuple, str] = {}  # (a,b) → status

    @property
    def name(self) -> str: return "cointegration_pairs"

    def on_bar(self, data: dict) -> list:
        return []  # Event-driven — use screen_and_trade()

    def screen_and_trade(self, price_df: pd.DataFrame) -> list[dict]:
        """Screen pairs and generate trade signals."""
        pairs = find_cointegrated_pairs(
            price_df, self.corr_min, self.hl_min, self.hl_max)
        signals = []

        for a, b, hedge, hl, corr, pval in pairs:
            spread = price_df[b] - hedge * price_df[a]
            mean = spread.mean()
            std = spread.std()
            if std <= 0:
                continue
            z_score = (spread.iloc[-1] - mean) / std
            key = (a, b)

            if key not in self._active and abs(z_score) > self.z_entry:
                side = "long_spread" if z_score < -self.z_entry else "short_spread"
                self._active[key] = side
                signals.append({
                    "signal": side, "pair_a": a, "pair_b": b,
                    "hedge_ratio": hedge, "z_score": z_score,
                    "half_life": hl, "reason": f"z={z_score:.2f} entry",
                })
            elif key in self._active and abs(z_score) < self.z_exit:
                signals.append({
                    "signal": "close", "pair_a": a, "pair_b": b,
                    "reason": f"z={z_score:.2f} exit",
                })
                del self._active[key]

        return signals

    def on_close(self) -> None:
        self._active.clear()


class LeveragedETFStrategy(BaseStrategy):
    """杠杆 ETF 趋势追踪 (unchanged from v1)."""

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.ema_fast      = cfg.get("ema_fast", 20)
        self.ema_slow      = cfg.get("ema_slow", 50)
        self.vol_stop_atr  = cfg.get("vol_stop_atr", 2.0)
        self.max_hold_days = cfg.get("max_hold_days", 20)

    @property
    def name(self) -> str: return "leveraged_etf"

    def on_bar(self, data: dict) -> list: return []
    def on_close(self) -> None: pass
