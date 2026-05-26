"""
策略融合引擎 — 多策略信号归一化 → 加权/投票 → 统一执行。

Usage:
    from core.ensemble import EnsembleEngine
    ee = EnsembleEngine(method="weighted")
    signal = ee.blend([("momentum", 0.6), ("grid", 0.3), ("long_term", 0.1)])
"""

import logging
import numpy as np
from config.settings import ENSEMBLE_METHOD, ENSEMBLE_LOOKBACK, ENSEMBLE_MIN_SIGNAL

log = logging.getLogger(__name__)


class EnsembleEngine:
    """Blend signals from multiple strategies into a single execution decision."""

    def __init__(self, method=ENSEMBLE_METHOD):
        self.method = method
        self._perf_history: dict[str, list[float]] = {}

    def record_pnl(self, strategy_name: str, pnl: float):
        """Record realized P&L for performance-based weighting."""
        if strategy_name not in self._perf_history:
            self._perf_history[strategy_name] = []
        self._perf_history[strategy_name].append(pnl)
        # Keep rolling window
        if len(self._perf_history[strategy_name]) > ENSEMBLE_LOOKBACK:
            self._perf_history[strategy_name] = self._perf_history[strategy_name][-ENSEMBLE_LOOKBACK:]

    def blend(self, signals: list[tuple[str, float]]) -> dict:
        """
        Blend strategy signals into one decision.

        Args:
            signals: [(strategy_name, signal_strength), ...]
                     signal_strength in [-1, 1]: -1=strong sell, 1=strong buy

        Returns:
            {"signal": "buy"|"sell"|"hold", "strength": float}
        """
        if not signals:
            return {"signal": "hold", "strength": 0.0}

        if self.method == "equal":
            blended = np.mean([s[1] for s in signals])

        elif self.method == "weighted":
            weights = []
            for name, strength in signals:
                history = self._perf_history.get(name, [])
                if len(history) >= 10:
                    sharpe = np.mean(history) / (np.std(history) + 1e-8)
                    w = max(0.1, sharpe)
                else:
                    w = 1.0 / len(signals)
                weights.append(w)
            total_w = sum(weights) or 1.0
            blended = sum(s[1] * weights[i] / total_w for i, s in enumerate(signals))

        elif self.method == "voting":
            votes = [1 if s[1] > ENSEMBLE_MIN_SIGNAL else (-1 if s[1] < -ENSEMBLE_MIN_SIGNAL else 0)
                     for s in signals]
            blended = np.mean(votes)

        else:
            blended = np.mean([s[1] for s in signals])

        blended = np.clip(blended, -1.0, 1.0)

        if blended > ENSEMBLE_MIN_SIGNAL:
            signal = "buy"
        elif blended < -ENSEMBLE_MIN_SIGNAL:
            signal = "sell"
        else:
            signal = "hold"

        return {"signal": signal, "strength": round(float(blended), 4)}
