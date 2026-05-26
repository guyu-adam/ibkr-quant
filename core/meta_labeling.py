"""
Meta-Labeling 过滤器 — 用二分类器判断信号质量，只执行高置信度交易。

基于 mlfinlab 的三重屏障法: 每笔交易标记为 1(盈利)/0(亏损),
训练 LightGBM 二分类器, 新信号通过分类器过滤。

Usage:
    from core.meta_labeling import MetaLabeler
    ml = MetaLabeler()
    ml.record_trade(features, pnl)    # 积累训练数据
    ok = ml.filter_signal(features)   # True = 执行, False = 跳过
"""

import logging
import numpy as np
import pandas as pd
from config.settings import META_LABEL_CONFIDENCE

log = logging.getLogger(__name__)


class MetaLabeler:
    """Binary classifier that filters low-quality trade signals."""

    def __init__(self, confidence=META_LABEL_CONFIDENCE):
        self.confidence = confidence
        self._model = None
        self._X: list[np.ndarray] = []
        self._y: list[int] = []
        self._trained = False
        self._min_samples = 100

    def record_trade(self, features: dict, pnl: float, horizon_days: int = 5):
        """
        Record a completed trade for training.

        Args:
            features: dict of feature_name → value at trade entry
            pnl: realized P&L (positive = win)
            horizon_days: how long the trade was held
        """
        # Triple-barrier style: label = 1 if profitable, 0 otherwise
        label = 1 if pnl > 0 else 0
        if self._X and len(features) != len(self._X[0]):
            return  # feature dimension mismatch

        self._X.append(np.array(list(features.values()), dtype=float))
        self._y.append(label)

    def filter_signal(self, features: dict) -> bool:
        """
        Returns True if the signal passes the meta-label filter.
        If untrained, allows all signals through.
        """
        if not self._trained:
            if len(self._y) >= self._min_samples:
                self._train()
            else:
                return True  # not enough data → allow

        if self._model is None:
            return True

        X = np.array(list(features.values()), dtype=float).reshape(1, -1)
        try:
            proba = self._model.predict_proba(X)[0]
            win_prob = proba[1] if len(proba) > 1 else proba[0]
            return win_prob >= self.confidence
        except Exception as e:
            log.error(f"Meta-label filter failed: {e} — rejecting signal")
            return False

    def _train(self):
        """Train LightGBM binary classifier on recorded trades."""
        try:
            import lightgbm as lgb
            X = np.array(self._X)
            y = np.array(self._y)

            if len(set(y)) < 2:
                log.warning("Meta-label: need both win and loss samples to train")
                return

            self._model = lgb.LGBMClassifier(
                n_estimators=100, max_depth=5, num_leaves=15,
                min_child_samples=20, verbose=-1, random_state=42,
            )
            self._model.fit(X, y)
            self._trained = True
            log.info(f"Meta-label trained: {len(y)} samples, "
                     f"win_rate={y.mean():.1%}")
        except ImportError:
            log.warning("lightgbm not installed — meta-label disabled")
        except Exception as e:
            log.warning(f"Meta-label training failed: {e}")
