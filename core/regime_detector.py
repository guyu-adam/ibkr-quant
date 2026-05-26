"""
HMM 市场状态检测 — 识别趋势/震荡/高波动，动态切换策略参数。

Usage:
    from core.regime_detector import RegimeDetector
    rd = RegimeDetector(n_states=3)
    regime = rd.fit_predict(prices)  # returns 0=trend-up, 1=sideways, 2=trend-down
"""

import logging
import numpy as np
import pandas as pd
from config.settings import HMM_N_STATES, HMM_LOOKBACK, HMM_RETRAIN_FREQ, HMM_FEATURES

log = logging.getLogger(__name__)


class RegimeDetector:
    """HMM-based market regime detection."""

    def __init__(self, n_states=HMM_N_STATES):
        self.n_states = n_states
        self._model = None
        self._last_regime = 0
        self._days_since_train = 0

    def _build_features(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        feats = pd.DataFrame(index=df.index)
        feats["ret_1d"]  = close.pct_change(1)
        feats["ret_5d"]  = close.pct_change(5)
        feats["ret_21d"] = close.pct_change(21)
        feats["vol_5d"]  = feats["ret_1d"].rolling(5).std()
        feats["vol_21d"] = feats["ret_1d"].rolling(21).std()
        feats["rsi_14"]  = self._rsi(close, 14)
        return feats.dropna()

    @staticmethod
    def _rsi(close: pd.Series, period: int) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(span=period, adjust=False).mean()
        loss = (-delta).clip(lower=0).ewm(span=period, adjust=False).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100.0 - 100.0 / (1.0 + rs)

    def fit_predict(self, df: pd.DataFrame) -> int:
        """Fit HMM on price history, return current regime label."""
        features = self._build_features(df.tail(HMM_LOOKBACK))
        if len(features) < 60:
            return self._last_regime

        self._days_since_train += 1
        if self._model is not None and self._days_since_train < HMM_RETRAIN_FREQ:
            try:
                self._last_regime = int(self._model.predict(features.iloc[-1:].values)[0])
            except Exception:
                pass
            return self._last_regime

        try:
            from hmmlearn import hmm
            X = features.values
            model = hmm.GaussianHMM(
                n_components=self.n_states, covariance_type="full",
                n_iter=1000, random_state=42,
            )
            model.fit(X)
            self._model = model
            self._days_since_train = 0

            states = model.predict(X)

            # Label states by mean return
            state_returns = {}
            for s in range(self.n_states):
                mask = states == s
                if mask.sum() > 5:
                    state_returns[s] = features["ret_21d"].iloc[mask].mean()

            # Sort: best return = state 0 (trend-up), worst = state N-1 (trend-down)
            sorted_states = sorted(state_returns, key=state_returns.get, reverse=True)
            state_map = {old: new for new, old in enumerate(sorted_states)}
            self._last_regime = state_map[states[-1]]

            log.info(f"HMM trained: {len(X)} samples, states labeled by 21d return")
        except ImportError:
            log.warning("hmmlearn not installed — regime detection disabled")
        except Exception as e:
            log.warning(f"HMM training failed: {e}")

        return self._last_regime

    def is_mean_reverting(self) -> bool:
        """True if current regime is sideways (state 1)."""
        return self._last_regime == 1

    def is_trending_up(self) -> bool:
        return self._last_regime == 0

    def is_trending_down(self) -> bool:
        return self._last_regime >= 2
