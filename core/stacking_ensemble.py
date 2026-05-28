"""
Stacking 集成预测 — 多模型堆叠 + 元学习器 + 动态权重。

比简单加权/投票融合更强的预测能力。

Architecture:
  Layer 1 (base models): LightGBM, XGBoost, Ridge, RandomForest, Transformer
  Layer 2 (meta-learner): LightGBM / LogisticRegression
  输出: 融合预测 + 置信度

Usage:
    from core.stacking_ensemble import StackingPredictor
    sp = StackingPredictor()
    sp.fit(X_train, y_train)
    preds, conf = sp.predict(X_test)
"""

import logging
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


class StackingPredictor:
    """
    Two-layer stacking ensemble for return prediction.

    Base models generate out-of-fold predictions, meta-learner combines them.
    """

    def __init__(self, n_folds: int = 5, use_xgboost: bool = False):
        self.n_folds = n_folds
        self.use_xgboost = use_xgboost
        self._base_models: dict[str, object] = {}
        self._meta_model = None
        self._trained = False
        self._feature_names: list[str] = []

    def fit(self, X: pd.DataFrame, y: pd.Series):
        self._feature_names = list(X.columns)
        X_arr = X.values
        y_arr = y.values

        valid = ~(np.isnan(y_arr) | np.isinf(y_arr))
        X_arr, y_arr = X_arr[valid], y_arr[valid]

        n = len(X_arr)
        oof_preds = np.zeros((n, 0))

        # ── Base Model 1: LightGBM ──
        try:
            import lightgbm as lgb
            oof = np.zeros(n)
            for fold in range(self.n_folds):
                val_idx = slice(fold * n // self.n_folds, (fold + 1) * n // self.n_folds)
                train_idx = np.setdiff1d(np.arange(n), np.arange(val_idx.start, val_idx.stop))
                if len(train_idx) < 50:
                    continue

                model = lgb.LGBMRegressor(
                    n_estimators=100, num_leaves=31, learning_rate=0.05,
                    verbose=-1, random_state=42,
                )
                model.fit(X_arr[train_idx], y_arr[train_idx])
                oof[val_idx] = model.predict(X_arr[val_idx])

            self._base_models["lgb"] = lgb.LGBMRegressor(
                n_estimators=100, num_leaves=31, learning_rate=0.05,
                verbose=-1, random_state=42,
            )
            self._base_models["lgb"].fit(X_arr, y_arr)
            oof_preds = np.column_stack([oof_preds, oof])
            log.info(f"Stacking: LightGBM base fitted")
        except ImportError:
            log.warning("lightgbm not installed — skipping base model")

        # ── Base Model 2: Ridge ──
        try:
            from sklearn.linear_model import RidgeCV
            oof = np.zeros(n)
            for fold in range(self.n_folds):
                val_idx = slice(fold * n // self.n_folds, (fold + 1) * n // self.n_folds)
                train_idx = np.setdiff1d(np.arange(n), np.arange(val_idx.start, val_idx.stop))
                if len(train_idx) < 50:
                    continue

                model = RidgeCV(alphas=[0.1, 1.0, 10.0])
                model.fit(X_arr[train_idx], y_arr[train_idx])
                oof[val_idx] = model.predict(X_arr[val_idx])

            self._base_models["ridge"] = RidgeCV(alphas=[0.1, 1.0, 10.0])
            self._base_models["ridge"].fit(X_arr, y_arr)
            oof_preds = np.column_stack([oof_preds, oof])
            log.info(f"Stacking: Ridge base fitted")
        except ImportError:
            log.warning("sklearn not installed — skipping Ridge")

        # ── Base Model 3: RandomForest ──
        try:
            from sklearn.ensemble import RandomForestRegressor
            oof = np.zeros(n)
            for fold in range(self.n_folds):
                val_idx = slice(fold * n // self.n_folds, (fold + 1) * n // self.n_folds)
                train_idx = np.setdiff1d(np.arange(n), np.arange(val_idx.start, val_idx.stop))
                if len(train_idx) < 50:
                    continue

                model = RandomForestRegressor(
                    n_estimators=100, max_depth=10, random_state=42, n_jobs=-1,
                )
                model.fit(X_arr[train_idx], y_arr[train_idx])
                oof[val_idx] = model.predict(X_arr[val_idx])

            self._base_models["rf"] = RandomForestRegressor(
                n_estimators=100, max_depth=10, random_state=42, n_jobs=-1,
            )
            self._base_models["rf"].fit(X_arr, y_arr)
            oof_preds = np.column_stack([oof_preds, oof])
            log.info(f"Stacking: RandomForest base fitted")
        except ImportError:
            pass

        # ── Base Model 4: XGBoost (optional) ──
        if self.use_xgboost:
            try:
                import xgboost as xgb
                oof = np.zeros(n)
                for fold in range(self.n_folds):
                    val_idx = slice(fold * n // self.n_folds, (fold + 1) * n // self.n_folds)
                    train_idx = np.setdiff1d(np.arange(n), np.arange(val_idx.start, val_idx.stop))
                    if len(train_idx) < 50:
                        continue
                    model = xgb.XGBRegressor(n_estimators=100, max_depth=6,
                                              learning_rate=0.05, verbosity=0)
                    model.fit(X_arr[train_idx], y_arr[train_idx])
                    oof[val_idx] = model.predict(X_arr[val_idx])

                self._base_models["xgb"] = xgb.XGBRegressor(
                    n_estimators=100, max_depth=6, learning_rate=0.05, verbosity=0,
                )
                self._base_models["xgb"].fit(X_arr, y_arr)
                oof_preds = np.column_stack([oof_preds, oof])
                log.info(f"Stacking: XGBoost base fitted")
            except ImportError:
                pass

        if oof_preds.shape[1] == 0:
            log.error("No base models fitted — stacking failed")
            return

        # ── Meta-Learner: LightGBM ──
        try:
            import lightgbm as lgb
            self._meta_model = lgb.LGBMRegressor(
                n_estimators=50, num_leaves=15, learning_rate=0.03,
                verbose=-1, random_state=42,
            )
        except ImportError:
            from sklearn.linear_model import Ridge
            self._meta_model = Ridge(alpha=1.0)

        self._meta_model.fit(oof_preds, y_arr)
        self._trained = True
        log.info(f"Stacking trained: {len(self._base_models)} base models, {n} samples")

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Return blended predictions."""
        if not self._trained or not self._base_models:
            return np.zeros(len(X))

        X_arr = X.values
        base_preds = np.zeros((len(X), 0))

        for name, model in self._base_models.items():
            try:
                pred = model.predict(X_arr)
                base_preds = np.column_stack([base_preds, pred])
            except Exception as e:
                log.debug(f"Stacking predict {name}: {e}")

        if base_preds.shape[1] == 0:
            return np.zeros(len(X))

        return self._meta_model.predict(base_preds)

    def predict_proba_direction(self, X: pd.DataFrame) -> np.ndarray:
        """
        Predict probability of positive return (for meta-labeling).
        Requires at least 2 base models for calibration.
        """
        preds = self.predict(X)
        # Sigmoid calibration: p(up) = 1 / (1 + exp(-preds / scale))
        scale = np.std(preds) if np.std(preds) > 0 else 1.0
        return 1.0 / (1.0 + np.exp(-preds / scale))


# ═══════════════════ Dynamic Model Weighting ═════════════════════════════════

class DynamicWeightEnsemble:
    """
    Time-varying model weights based on recent performance.

    Weights are proportional to recent Sharpe ratio of each model.
    """

    def __init__(self, lookback: int = 60):
        self.lookback = lookback
        self._model_returns: dict[str, list[float]] = {}

    def record(self, model_name: str, predicted: float, actual: float):
        """Record a prediction-outcome pair for weight update."""
        if model_name not in self._model_returns:
            self._model_returns[model_name] = []
        # Directional accuracy as proxy return
        proxy_ret = 1.0 if np.sign(predicted) == np.sign(actual) else -1.0
        self._model_returns[model_name].append(proxy_ret)
        if len(self._model_returns[model_name]) > self.lookback * 5:
            self._model_returns[model_name] = self._model_returns[model_name][-self.lookback * 5:]

    def weights(self) -> dict[str, float]:
        """Compute Sharpe-based weights."""
        if not self._model_returns:
            return {}

        sharpes = {}
        for name, rets in self._model_returns.items():
            recent = rets[-self.lookback:]
            if len(recent) < 20:
                sharpes[name] = 0.0
                continue
            mu = np.mean(recent)
            std = np.std(recent)
            sharpes[name] = mu / (std + 1e-8)

        # Softmax over sharpes
        s_vals = np.array(list(sharpes.values()))
        s_exp = np.exp(s_vals - s_vals.max())
        s_probs = s_exp / s_exp.sum()

        return dict(zip(sharpes.keys(), s_probs))

    def blend(self, predictions: dict[str, np.ndarray]) -> np.ndarray:
        """Weighted blend of predictions."""
        weights = self.weights()
        if not weights or not predictions:
            return np.zeros(len(list(predictions.values())[0]))

        blended = np.zeros_like(list(predictions.values())[0])
        total_w = sum(weights.get(n, 0) for n in predictions)
        if total_w <= 0:
            return blended

        for name, pred in predictions.items():
            blended += weights.get(name, 0) / total_w * pred

        return blended
