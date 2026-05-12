"""
Portfolio optimization — based on PyPortfolioOpt.

Each function takes a returns DataFrame (tickers × dates, indexed by date)
and returns a weight allocation Series.
"""

import numpy as np
import pandas as pd
from pypfopt import EfficientFrontier, risk_models, expected_returns
from scipy.optimize import minimize


def _validate(returns_df: pd.DataFrame) -> pd.DataFrame:
    df = returns_df.replace([np.inf, -np.inf], np.nan).dropna()
    if len(df) < 30:
        raise ValueError(f"Need at least 30 valid return observations, got {len(df)}")
    return df


def _expected_returns(df: pd.DataFrame) -> pd.Series:
    mu = expected_returns.capm_return(df)
    if mu.isna().any() or (mu <= 0).all():
        mu = df.mean() * 252
    return mu


def max_sharpe(returns_df: pd.DataFrame, risk_free_rate: float = 0.02) -> pd.Series:
    """Maximum Sharpe ratio portfolio weights."""
    df = _validate(returns_df)
    mu = _expected_returns(df)
    S = risk_models.sample_cov(df)
    ef = EfficientFrontier(mu, S)
    weights = ef.max_sharpe(risk_free_rate=risk_free_rate)
    return pd.Series(ef.clean_weights(), name="weight").sort_values(ascending=False)


def min_volatility(returns_df: pd.DataFrame) -> pd.Series:
    """Minimum volatility / global-minimum-variance portfolio weights."""
    df = _validate(returns_df)
    mu = _expected_returns(df)
    S = risk_models.sample_cov(df)
    ef = EfficientFrontier(mu, S)
    weights = ef.min_volatility()
    return pd.Series(ef.clean_weights(), name="weight").sort_values(ascending=False)


def risk_parity(returns_df: pd.DataFrame) -> pd.Series:
    """Equal risk contribution (risk parity) portfolio weights.

    Minimises the squared deviation of each asset's risk contribution
    from the equal-risk target.
    """
    df = _validate(returns_df)
    S = risk_models.sample_cov(df).values
    n = len(S)
    labels = df.columns

    def _risk_budget_objective(w):
        w = np.array(w)
        port_vol = np.sqrt(w @ S @ w)
        marginal = S @ w
        risk_contrib = w * marginal / port_vol
        target = port_vol / n
        return np.sum((risk_contrib - target) ** 2)

    w0 = np.ones(n) / n
    bounds = [(0, 1)] * n
    cons = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
    result = minimize(
        _risk_budget_objective, w0, bounds=bounds, constraints=cons,
        method="SLSQP", options={"maxiter": 2000, "ftol": 1e-12}
    )
    return pd.Series(result.x, index=labels, name="weight").sort_values(ascending=False)
