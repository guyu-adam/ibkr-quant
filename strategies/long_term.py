"""
长期策略 — 被动组合管理、月度再平衡、定投加仓、移动止损。

Usage:
    from strategies.long_term import LongTermPortfolio
    portfolio = LongTermPortfolio(broker, risk_mgr, portfolio_cfg)
    portfolio.rebalance(dry_run=True)
"""

import logging
import pandas as pd
import yfinance as yf

from core.strategy_base import BaseStrategy

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


def rebalance_trades(current_positions, target_weights, prices, equity,
                     drift_threshold=0.05) -> list[dict]:
    trades = []
    total_val = sum(current_positions.get(t, 0) * prices.get(t, 0) for t in target_weights)
    portfolio_val = max(total_val, equity)

    for ticker, target_wt in target_weights.items():
        price = prices.get(ticker, 0.0)
        if price <= 0:
            continue
        current_shares = current_positions.get(ticker, 0)
        current_val = current_shares * price
        current_wt = current_val / portfolio_val if portfolio_val > 0 else 0
        drift = target_wt - current_wt

        if abs(drift) < drift_threshold:
            continue

        target_shares = int(portfolio_val * target_wt / price)
        delta = target_shares - current_shares
        if delta == 0:
            continue

        trades.append({"action": "BUY" if delta > 0 else "SELL",
                       "ticker": ticker, "shares": abs(delta),
                       "price": price, "drift": drift})

    return trades


class LongTermPortfolio(BaseStrategy):
    """
    长期组合策略 — 月度再平衡 + 定投 + 移动止损。

    Config keys:
        positions (dict):         {"QQQ": 0.30, "SPY": 0.20, ...}
        drift_threshold (0.05):   rebalance when drift > 5%
        dca_dip_pct (0.10):       DCA if price > 10% below 52w high
        trailing_stop_pct (0.20): exit at 20% drawdown from peak
        max_equity_pct (0.60):    max 60% of account in long-term bucket
    """

    def __init__(self, broker, risk_mgr, portfolio_cfg: dict):
        self.broker = broker
        self.risk_mgr = risk_mgr
        self.cfg = portfolio_cfg
        self._peaks: dict[str, float] = {}

    @property
    def name(self) -> str:
        return "long_term"

    def on_bar(self, data: dict) -> list:
        return []

    def on_close(self) -> None:
        pass

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
            val = qty * p
            rows.append({"ticker": t, "shares": qty, "price": round(p, 2),
                         "market_val": round(val, 2),
                         "current_wt": round(val / equity, 4) if equity > 0 else 0,
                         "target_wt": round(weights[t], 4)})
        return pd.DataFrame(rows)

    def rebalance(self, dry_run=False) -> list[dict]:
        weights = compute_target_weights(self.cfg["positions"])
        tickers = list(weights.keys())
        prices = get_current_prices(tickers)
        equity = (self.broker.net_liquidation() or 100000) * self.cfg.get("max_equity_pct", 0.6)
        current = self.broker.positions()

        trades = rebalance_trades(
            current, weights, prices, equity,
            drift_threshold=self.cfg.get("drift_threshold", 0.05),
        )

        for t in trades:
            if dry_run:
                log.info(f"[DRY_RUN] {t['action']} {t['shares']} {t['ticker']} @ {t['price']:.2f}")
                continue
            if not self.risk_mgr.approve(t["ticker"], t["shares"], t["price"]):
                continue
            try:
                self.broker.market_order(t["ticker"], t["shares"], t["action"])
            except Exception as e:
                log.error(f"[REBAL] {t['ticker']}: {e}")

        return trades

    def check_trailing_stops(self):
        stop_pct = self.cfg.get("trailing_stop_pct", 0.20)
        for ticker, qty in self.broker.positions().items():
            if ticker not in self.cfg["positions"] or qty <= 0:
                continue
            try:
                price = self.broker.last_price(ticker)
                if price <= 0:
                    continue
                peak = self._peaks.get(ticker, price)
                if price > peak:
                    self._peaks[ticker] = price
                    peak = price
                if (peak - price) / peak > stop_pct:
                    log.warning(f"[LT_STOP] {ticker} drawdown → closing")
                    self.broker.market_order(ticker, qty, "SELL")
            except Exception as e:
                log.debug(f"[LT_STOP] {ticker}: {e}")

    def dca_dips(self):
        dip_pct = self.cfg.get("dca_dip_pct", 0.10)
        weights = compute_target_weights(self.cfg["positions"])
        equity = self.broker.net_liquidation() or 100000

        for ticker, weight in weights.items():
            try:
                hist = yf.Ticker(ticker).history(period="52wk")
                if hist.empty:
                    continue
                high_52w = hist["High"].max()
                last = float(hist["Close"].iloc[-1])
                if high_52w <= 0 or (high_52w - last) / high_52w < dip_pct:
                    continue
                extra_val = equity * weight * 0.5
                shares = int(extra_val / last)
                if shares <= 0:
                    continue
                if not self.risk_mgr.approve(ticker, shares, last):
                    continue
                log.info(f"[DCA] {ticker} dip → BUY {shares}")
                self.broker.market_order(ticker, shares, "BUY")
            except Exception as e:
                log.debug(f"[DCA] {ticker}: {e}")
