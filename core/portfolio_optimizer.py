"""
组合优化器 — 基于 Riskfolio-Lib / scipy

支持:
  - 风险平价 (Risk Parity)
  - 最大夏普 (Max Sharpe)
  - 最小方差 (Min Variance)
  - 等权 (Equal Weight)
"""

import numpy as np
import pandas as pd
import logging

log = logging.getLogger(__name__)

try:
    import riskfolio as rp
    HAS_RISKFOLIO = True
except ImportError:
    HAS_RISKFOLIO = False
    log.warning("riskfolio 未安装，使用 scipy 实现")


def _cov_matrix(returns: pd.DataFrame, lookback: int = 63) -> pd.DataFrame:
    """计算协方差矩阵"""
    return returns.tail(lookback).cov()


def _expected_returns(alpha_scores: pd.Series) -> pd.Series:
    """将 alpha 得分映射为预期收益"""
    # 简单的线性映射：alpha > 0 → 正收益, alpha < 0 → 负收益
    return alpha_scores * 0.01  # 1% scaling


def optimize_portfolio(
    symbols: list[str],
    alpha_scores: pd.Series,
    price_history: pd.DataFrame,
    method: str = 'risk_parity',
    max_weight: float = 0.15,
    min_weight: float = 0.01,
) -> dict[str, float]:
    """
    组合优化主入口

    Args:
        symbols: 候选标的列表
        alpha_scores: 预期 alpha 得分
        price_history: 价格历史 DataFrame (columns=symbols, index=dates)
        method: 'risk_parity' | 'max_sharpe' | 'min_variance' | 'equal_weight'
        max_weight: 单票最大权重
        min_weight: 单票最小权重

    Returns:
        {symbol: weight} 权重字典
    """
    n = len(symbols)
    if n == 0:
        return {}

    if n == 1:
        return {symbols[0]: 1.0}

    # 计算收益率矩阵
    returns = price_history[symbols].pct_change().dropna()

    if len(returns) < 20:
        # 数据不足，等权
        w = 1.0 / n
        return {s: w for s in symbols}

    cov = _cov_matrix(returns)
    mu = _expected_returns(alpha_scores.loc[symbols] if not alpha_scores.empty
                           else pd.Series(0.02, index=symbols))

    if method == 'equal_weight':
        w = 1.0 / n
        return {s: w for s in symbols}

    if HAS_RISKFOLIO:
        try:
            return _riskfolio_optimize(returns, cov, mu, method, max_weight, min_weight)
        except Exception as e:
            log.warning(f"Riskfolio 优化失败: {e}，回退到 scipy")

    return _scipy_optimize(cov, mu, method, max_weight, min_weight, symbols)


def _scipy_optimize(
    cov: pd.DataFrame,
    mu: pd.Series,
    method: str,
    max_weight: float,
    min_weight: float,
    symbols: list[str],
) -> dict[str, float]:
    """基于 scipy 的优化"""
    from scipy.optimize import minimize

    n = len(symbols)
    cov_mat = cov.loc[symbols, symbols].values
    mu_vec = mu.loc[symbols].values
    init_w = np.ones(n) / n

    bounds = [(min_weight, max_weight) for _ in range(n)]
    constraints = [{'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}]

    def portfolio_vol(w):
        return np.sqrt(w @ cov_mat @ w)

    def neg_sharpe(w):
        ret = w @ mu_vec
        vol = np.sqrt(w @ cov_mat @ w)
        return -ret / vol if vol > 0 else 1e9

    def risk_parity_obj(w):
        # 风险贡献的方差
        port_vol = np.sqrt(w @ cov_mat @ w)
        if port_vol == 0:
            return 1e9
        mrc = cov_mat @ w / port_vol   # 边际风险贡献
        rc = w * mrc                    # 风险贡献
        target_rc = port_vol / n       # 目标（均等）
        return np.sum((rc - target_rc) ** 2)

    if method == 'min_variance':
        result = minimize(portfolio_vol, init_w, bounds=bounds,
                          constraints=constraints, method='SLSQP')
    elif method == 'max_sharpe':
        result = minimize(neg_sharpe, init_w, bounds=bounds,
                          constraints=constraints, method='SLSQP')
    else:  # risk_parity
        result = minimize(risk_parity_obj, init_w, bounds=bounds,
                          constraints=constraints, method='SLSQP')

    if result.success:
        weights = result.x
        weights = np.maximum(weights, 0)  # no negative
        weights = weights / weights.sum()  # normalize
        return {s: float(w) for s, w in zip(symbols, weights) if w > 0.001}
    else:
        log.warning(f"优化未收敛，使用等权")
        w = 1.0 / n
        return {s: w for s in symbols}


def _riskfolio_optimize(
    returns: pd.DataFrame,
    cov: pd.DataFrame,
    mu: pd.Series,
    method: str,
    max_weight: float,
    min_weight: float,
) -> dict[str, float]:
    """基于 Riskfolio-Lib 的优化"""
    import riskfolio as rp

    port = rp.Portfolio(returns=returns)

    port.assets_stats(
        method_mu='hist',
        method_cov='hist',
    )

    if method == 'max_sharpe':
        w = port.optimization(
            model='Classic',
            rm='MV',
            obj='Sharpe',
            hist=True,
            rf=0.02,  # 无风险利率
            l=0,
        )
    elif method == 'min_variance':
        w = port.optimization(
            model='Classic',
            rm='MV',
            obj='MinRisk',
            hist=True,
        )
    else:  # risk_parity
        w = port.rp_optimization(
            model='Classic',
            rm='MV',
            rf=0.02,
            hist=True,
        )

    weights = w['weights'].to_dict() if 'weights' in w else {}
    # Normalize
    total = sum(weights.values())
    if total > 0:
        weights = {k: v / total for k, v in weights.items()}
    return {k: v for k, v in weights.items() if v > 0.001}
