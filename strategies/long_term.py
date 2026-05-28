"""
长期策略 v2 — HRP 层级风险平价 + Bootstrap 稳健优化 + 月度再平衡。

Enhancements (P0/P1):
  - Hierarchical Risk Parity (HRP) replaces fixed weights
  - Ledoit-Wolf covariance shrinkage
  - Bootstrap worst-case optimization (5th percentile)
  - DCA + trailing stops (kept from v1)
"""

import logging
import numpy as np
import pandas as pd
import yfinance as yf

from core.strategy_base import BaseStrategy
from config.settings import LONG_TERM_PORTFOLIO

log = logging.getLogger(__name__)


def get_current_prices(tickers: list[str]) -> dict[str, float]:
    prices = {}
    for t in tickers:
        try:
            info = yf.Ticker(t).fast_info
            prices[t] = info.last_price or info.previous_close or 0.0
        except Exception:
            prices[t] = 0.0
    return prices


def compute_target_weights(portfolio: dict) -> dict[str, float]:
    total = sum(portfolio.values())
    return {k: v / total for k, v in portfolio.items()} if total > 0 else {}


def hrp_weights(prices_df: pd.DataFrame, method="ward",
                shrinkage="ledoit_wolf") -> dict[str, float]:
    """
    Hierarchical Risk Parity allocation.

    Args:
        prices_df: T x N DataFrame of historical prices
        method: linkage method (ward, single, complete, average)
        shrinkage: covariance shrinkage (ledoit_wolf, oas, sample)

    Returns:
        {ticker: weight} dict
    """
    returns = prices_df.pct_change().dropna()
    if len(returns) < 60:
        # Fall back to equal weight
        n = len(prices_df.columns)
        return {c: 1.0/n for c in prices_df.columns}

    try:
        from sklearn.covariance import LedoitWolf, OAS
        if shrinkage == "ledoit_wolf":
            cov = LedoitWolf().fit(returns.values).covariance_
        elif shrinkage == "oas":
            cov = OAS().fit(returns.values).covariance_
        else:
            cov = returns.cov().values

        from scipy.cluster.hierarchy import linkage, dendrogram
        from scipy.spatial.distance import squareform

        # Distance from correlation
        corr = returns.corr().values
        dist = np.sqrt(2 * (1 - corr))
        dist[np.diag_indices_from(dist)] = 0

        # Hierarchical clustering
        link = linkage(squareform(dist, checks=False), method=method)

        # Recursive bisection
        n = len(returns.columns)
        w = pd.Series(1.0, index=returns.columns)
        clusters = [(list(range(n)), 1.0)]

        # HRP via inverse-variance allocation per cluster
        for i in range(len(link)):
            c1, c2 = int(link[i, 0]), int(link[i, 1])
            c1_members = [j for j in range(n) if _in_cluster(link, j, c1)]
            c2_members = [j for j in range(n) if _in_cluster(link, j, c2)]

            # Only use clusters with at least 1 member
            if not c1_members or not c2_members:
                continue

            c1_cov = cov[np.ix_(c1_members, c1_members)]
            c2_cov = cov[np.ix_(c2_members, c2_members)]

            try:
                iv1 = 1.0 / np.sqrt(np.sum(np.linalg.inv(c1_cov))) if len(c1_members) > 1 else 1.0 / np.sqrt(c1_cov[0, 0])
                iv2 = 1.0 / np.sqrt(np.sum(np.linalg.inv(c2_cov))) if len(c2_members) > 1 else 1.0 / np.sqrt(c2_cov[0, 0])
            except np.linalg.LinAlgError:
                iv1 = iv2 = 0.5

            total_iv = iv1 + iv2
            if total_iv > 0:
                w.iloc[c1_members] *= iv1 / total_iv
                w.iloc[c2_members] *= iv2 / total_iv

        w = w / w.sum()
        return w.to_dict()

    except ImportError as e:
        log.warning(f"HRP requires scipy+sklearn: {e} — falling back to equal weight")
        n = len(prices_df.columns)
        return {c: 1.0/n for c in prices_df.columns}


def _in_cluster(link, target, node):
    """Iterative version — avoids recursion limit for large datasets."""
    n_original = len(link) + 1
    stack = [node]
    while stack:
        current = stack.pop()
        if current == target:
            return True
        if current < n_original:
            continue
        c1 = int(link[current - n_original, 0])
        c2 = int(link[current - n_original, 1])
        stack.append(c1)
        stack.append(c2)
    return False


def bootstrap_worst_case(returns: pd.DataFrame, n_samples=1000,
                         confidence=0.05) -> dict[str, float]:
    """
    Find portfolio weights that minimize worst-case drawdown.
    Uses bootstrap resampling to estimate 5th percentile scenario.
    """
    try:
        from scipy.optimize import minimize
        tickers = returns.columns
        n = len(tickers)

        # Bootstrap resampling
        boot_means = []
        for _ in range(n_samples):
            idx = np.random.choice(len(returns), len(returns), replace=True)
            boot_means.append(returns.iloc[idx].mean().values)

        boot_means = np.array(boot_means)

        def worst_case_return(w):
            w = np.abs(w) / np.abs(w).sum()  # normalize, no short
            portfolio_rets = boot_means @ w
            return -np.percentile(portfolio_rets, confidence * 100)

        constraints = [{"type": "eq", "fun": lambda w: np.sum(np.abs(w)) - 1.0}]
        bounds = [(0.01, 0.40) for _ in range(n)]
        result = minimize(worst_case_return, np.ones(n) / n,
                         method="SLSQP", bounds=bounds, constraints=constraints)

        if result.success:
            w = np.abs(result.x) / np.abs(result.x).sum()
            return dict(zip(tickers, w))
    except Exception as e:
        log.warning(f"Bootstrap optimization failed: {e}")

    return {t: 1.0/n for t in returns.columns}


class LongTermPortfolio(BaseStrategy):
    """长期组合 v2 — HRP/Bootstrap + DCA + trailing stops."""

    def __init__(self, broker, risk_mgr, portfolio_cfg=None):
        self.broker = broker
        self.risk_mgr = risk_mgr
        self.cfg = portfolio_cfg or LONG_TERM_PORTFOLIO
        self._peaks: dict[str, float] = {}

    @property
    def name(self) -> str: return "long_term"

    def on_bar(self, data: dict) -> list: return []
    def on_close(self) -> None: pass

    def allocate(self, prices_df: pd.DataFrame) -> dict[str, float]:
        """
        Compute target weights using configured method.

        Returns: {ticker: weight} dict
        """
        if self.cfg.get("use_hrp", True):
            return hrp_weights(
                prices_df,
                method=self.cfg.get("hrp_method", "ward"),
                shrinkage=self.cfg.get("cov_shrinkage", "ledoit_wolf"),
            )
        else:
            return compute_target_weights(self.cfg["positions"])

    def status(self) -> pd.DataFrame:
        weights = compute_target_weights(self.cfg["positions"])
        tickers = list(weights.keys())
        prices = get_current_prices(tickers)
        equity = self.broker.net_liquidation() or 100000
        current = self.broker.positions()
        rows = []
        for t in tickers:
            p = prices.get(t, 0)
            qty = current.get(t, 0)
            rows.append({"ticker": t, "shares": qty, "price": round(p, 2),
                         "market_val": round(qty * p, 2),
                         "current_wt": round(qty * p / equity, 4) if equity > 0 else 0,
                         "target_wt": round(weights[t], 4)})
        return pd.DataFrame(rows)

    def rebalance(self, dry_run=False) -> list[dict]:
        """Execute rebalancing using allocate() as the sole weight source."""
        tickers = list(self.cfg["positions"].keys())
        prices = get_current_prices(tickers)
        equity = (self.broker.net_liquidation() or 100_000) * self.cfg.get("max_equity_pct", 0.6)
        current = self.broker.positions()

        # Use allocate() as the single source of truth for weights
        try:
            hist = yf.download(tickers, period="1y", progress=False, auto_adjust=True)
            if not hist.empty and len(hist) > 60:
                close_df = hist["Close"]
                if isinstance(close_df, pd.Series):
                    close_df = close_df.to_frame()
                weights = self.allocate(close_df)
            else:
                weights = self.allocate(
                    pd.DataFrame({t: [prices.get(t, 0)] for t in tickers}).T
                )
        except Exception:
            weights = compute_target_weights(self.cfg["positions"])

        trades = []
        drift_threshold = self.cfg.get("drift_threshold", 0.05)
        for ticker, target_wt in weights.items():
            price = prices.get(ticker, 0.0)
            if price <= 0:
                continue
            current_wt = (current.get(ticker, 0) * price) / equity if equity > 0 else 0
            drift = target_wt - current_wt
            if abs(drift) < drift_threshold:
                continue
            delta = int(equity * drift / price)
            if delta == 0:
                continue
            action = "BUY" if delta > 0 else "SELL"
            if not dry_run and self.risk_mgr.approve(ticker, abs(delta), price):
                try:
                    self.broker.market_order(ticker, abs(delta), action)
                except Exception as e:
                    log.error(f"[REBAL] {ticker}: {e}")
            trades.append({"action": action, "ticker": ticker, "shares": abs(delta),
                           "price": price, "drift": drift})
        return trades

    def check_trailing_stops(self):
        stop_pct = self.cfg.get("trailing_stop_pct", 0.20)
        for ticker, qty in list(self.broker.positions().items()):
            if ticker not in self.cfg["positions"] or qty <= 0:
                continue
            try:
                price = self.broker.last_price(ticker)
                if price <= 0: continue
                peak = self._peaks.get(ticker, price)
                if price > peak: self._peaks[ticker] = peak = price
                if (peak - price) / peak > stop_pct:
                    log.warning(f"[LT_STOP] {ticker} → closing")
                    self.broker.market_order(ticker, qty, "SELL")
            except Exception as e:
                log.debug(f"[LT_STOP] {ticker}: {e}")

    def dca_dips(self):
        dip_pct = self.cfg.get("dca_dip_pct", 0.10)
        tickers = list(self.cfg["positions"].keys())
        try:
            hist = yf.download(tickers, period="1y", progress=False, auto_adjust=True)
            if not hist.empty and len(hist) > 60:
                close_df = hist["Close"]
                if isinstance(close_df, pd.Series):
                    close_df = close_df.to_frame()
                weights = self.allocate(close_df)
            else:
                weights = compute_target_weights(self.cfg["positions"])
        except Exception:
            weights = compute_target_weights(self.cfg["positions"])
        equity = self.broker.net_liquidation() or 100_000
        for ticker, weight in weights.items():
            try:
                hist = yf.Ticker(ticker).history(period="52wk")
                if hist.empty: continue
                high, last = hist["High"].max(), float(hist["Close"].iloc[-1])
                if high <= 0 or (high - last) / high < dip_pct: continue
                shares = int(equity * weight * 0.5 / last)
                if shares > 0 and self.risk_mgr.approve(ticker, shares, last):
                    log.info(f"[DCA] {ticker} dip → BUY {shares}")
                    self.broker.market_order(ticker, shares, "BUY")
            except Exception as e:
                log.debug(f"[DCA] {ticker}: {e}")
