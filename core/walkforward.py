"""
Walk-Forward 验证框架 — 滚动窗口参数优化 + 过拟合检测。

Usage:
    from core.walkforward import WalkForwardValidator
    wfv = WalkForwardValidator(strategy_class, param_grid, data)
    results = wfv.run()
"""

import logging
import numpy as np
import pandas as pd
from itertools import product
from config.settings import WF_IS_YEARS, WF_OOS_MONTHS, WF_STEP_MONTHS, WF_MAX_IS_OOS_RATIO

log = logging.getLogger(__name__)


class WalkForwardValidator:
    """Rolling IS/OOS validation to prevent overfitting."""

    def __init__(self, strategy_class, param_grid: dict, data: pd.DataFrame,
                 is_years=WF_IS_YEARS, oos_months=WF_OOS_MONTHS,
                 step_months=WF_STEP_MONTHS):
        self.strategy_class = strategy_class
        self.param_grid = param_grid
        self.data = data
        self.is_years = is_years
        self.oos_months = oos_months
        self.step_months = step_months
        self._results: list[dict] = []

    @property
    def param_combinations(self) -> list[dict]:
        keys = list(self.param_grid.keys())
        values = list(self.param_grid.values())
        return [dict(zip(keys, combo)) for combo in product(*values)]

    def _split_windows(self) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
        """Generate (is_start, is_end/oos_start, oos_end) tuples."""
        idx = self.data.index
        start = idx[0]
        end = idx[-1]
        windows = []
        is_len = pd.DateOffset(years=self.is_years)
        oos_len = pd.DateOffset(months=self.oos_months)
        step = pd.DateOffset(months=self.step_months)

        current = start + is_len
        while current + oos_len <= end:
            is_start = current - is_len
            windows.append((is_start, current, current + oos_len))
            current += step
        return windows

    def run(self) -> pd.DataFrame:
        """Execute walk-forward validation. Returns DataFrame with all windows."""
        windows = self._split_windows()
        if not windows:
            log.warning("Not enough data for walk-forward windows")
            return pd.DataFrame()

        log.info(f"Walk-forward: {len(windows)} windows, {len(self.param_combinations)} param combos")

        for is_start, is_end, oos_end in windows:
            is_data = self.data[is_start:is_end]
            oos_data = self.data[is_end:oos_end]
            if len(is_data) < 60 or len(oos_data) < 20:
                continue

            best_params = None
            best_is_sharpe = -999

            for params in self.param_combinations:
                strategy = self.strategy_class(params)
                is_sharpe = self._evaluate(strategy, is_data)
                if is_sharpe > best_is_sharpe:
                    best_is_sharpe = is_sharpe
                    best_params = params

            strategy = self.strategy_class(best_params)
            oos_sharpe = self._evaluate(strategy, oos_data)
            ratio = best_is_sharpe / (oos_sharpe + 1e-8)

            self._results.append({
                "is_start": is_start, "is_end": is_end, "oos_end": oos_end,
                "best_params": str(best_params), "is_sharpe": round(best_is_sharpe, 3),
                "oos_sharpe": round(oos_sharpe, 3), "is_oos_ratio": round(ratio, 2),
                "overfit": abs(ratio) > WF_MAX_IS_OOS_RATIO,
            })

        df = pd.DataFrame(self._results)
        if not df.empty:
            avg_oos = df["oos_sharpe"].mean()
            overfit_pct = df["overfit"].sum() / len(df)
            log.info(f"WF avg OOS Sharpe={avg_oos:.3f}, overfit windows={overfit_pct:.0%}")

        return df

    def _evaluate(self, strategy, data: pd.DataFrame) -> float:
        """Simple strategy evaluation returning Sharpe-like metric."""
        try:
            signals = []
            for i in range(60, len(data)):
                sub = data.iloc[:i+1]
                try:
                    result = strategy.evaluate(
                        type("Feed", (), {"fetch_history": lambda s, p="6mo", iv="1d": sub})(),
                        data.index.name or "SYM",
                    )
                    signals.append(1 if result.get("signal") == "buy" else
                                  (-1 if result.get("signal") == "sell" else 0))
                except Exception:
                    signals.append(0)

            if not signals or len(set(signals)) == 1:
                return 0.0

            rets = data["close"].pct_change().iloc[-len(signals):].values
            strat_rets = np.array(signals) * rets
            sr = np.mean(strat_rets) / (np.std(strat_rets) + 1e-8) * np.sqrt(252)
            return float(sr)
        except Exception:
            return 0.0
