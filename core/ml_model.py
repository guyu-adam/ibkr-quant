"""
量化 ML 模型 — 基于 LightGBM 的收益预测

训练 → 预测 → 排序 → 选股
"""

import numpy as np
import pandas as pd
from typing import Optional
import logging

log = logging.getLogger(__name__)


class AlphaModel:
    """
    多因子 Alpha 预测模型（LightGBM）

    训练: 因子 X → 未来收益 y
    预测: 新因子 X → 预期收益排序 → 做多前K/做空后K
    """

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.horizon       = cfg.get('horizon', 5)         # 预测未来 N 日
        self.top_k          = cfg.get('top_k', 20)          # 做多前 K 只
        self.bottom_k       = cfg.get('bottom_k', 10)       # 做空后 K 只
        self.retrain_freq   = cfg.get('retrain_freq', 21)   # 每 N 天重训
        self.min_train_days  = cfg.get('min_train_days', 252) # 最少训练天数
        self._model          = None
        self._feature_names  = None

    def train(self, X: pd.DataFrame, y: pd.Series):
        """训练 LightGBM 模型"""
        try:
            import lightgbm as lgb
        except ImportError:
            log.warning("lightgbm 未安装，使用 Ridge 回归")
            return self._train_ridge(X, y)

        # 过滤无效标签
        valid = ~(y.isna() | np.isinf(y))
        X_v, y_v = X.loc[valid], y.loc[valid]
        if len(X_v) < self.min_train_days:
            log.warning(f"训练数据不足: {len(X_v)} < {self.min_train_days}")
            return

        self._feature_names = list(X_v.columns)
        train_data = lgb.Dataset(X_v.values, label=y_v.values)

        params = {
            'objective': 'regression',
            'metric': 'rmse',
            'boosting_type': 'gbdt',
            'num_leaves': 31,
            'learning_rate': 0.05,
            'feature_fraction': 0.8,
            'bagging_fraction': 0.8,
            'bagging_freq': 5,
            'verbose': -1,
            'seed': 42,
        }

        self._model = lgb.train(params, train_data, num_boost_round=100)
        log.info(f"LightGBM 训练完成: {len(X_v)} 样本, {len(self._feature_names)} 因子")

    def _train_ridge(self, X, y):
        """备选: Ridge 回归"""
        from sklearn.linear_model import Ridge
        valid = ~(y.isna() | np.isinf(y))
        X_v, y_v = X.loc[valid], y.loc[valid]
        if len(X_v) < self.min_train_days:
            return
        self._feature_names = list(X_v.columns)
        self._model = Ridge(alpha=1.0)
        self._model.fit(X_v.values, y_v.values)
        log.info(f"Ridge 训练完成: {len(X_v)} 样本")

    def predict(self, X: pd.DataFrame) -> pd.Series:
        """预测预期收益"""
        if self._model is None or self._feature_names is None:
            return pd.Series(0.0, index=X.index)

        # 按训练时的列顺序对齐，缺失列填 0
        X_aligned = X.reindex(columns=self._feature_names, fill_value=0.0)
        preds = self._model.predict(X_aligned.values)

        return pd.Series(preds, index=X_aligned.index, name='alpha')

    def select_top(self, alpha_scores: pd.Series) -> tuple[list, list]:
        """
        根据 alpha 得分选择持仓

        Returns:
            long_list: 做多列表
            short_list: 做空列表
        """
        ranked = alpha_scores.sort_values(ascending=False)
        longs  = list(ranked.head(self.top_k).index)
        shorts = list(ranked.tail(self.bottom_k).index)
        return longs, shorts

    @property
    def is_trained(self) -> bool:
        return self._model is not None
