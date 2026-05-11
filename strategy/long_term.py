"""
Long-Term Portfolio Manager
────────────────────────────
Manages a basket of ETFs and growth stocks with:
  - Equal-weight or custom-weight allocation
  - Monthly rebalancing (drift-triggered)
  - Dollar-cost averaging on dips (optional)
  - Trailing stop for individual positions

Designed to run alongside short-term strategies as a separate "account bucket".
Configure weights in config/settings.py → LONG_TERM_PORTFOLIO.
"""

import logging
from datetime import date, datetime
from typing import Optional

import yfinance as yf
import pandas as pd

log = logging.getLogger(__name__)


# ── portfolio analysis (no IBKR required) ─────────────────────────────────────

def get_current_prices(tickers: list[str]) -> dict[str, float]:
    """Fetch latest close for each ticker via yfinance."""
    prices = {}
    for t in tickers:
        try:
            info = yf.Ticker(t).fast_info
            prices[t] = info.last_price or info.previous_close or 0.0
        except Exception:
            prices[t] = 0.0
    return prices


def compute_target_weights(portfolio: dict) -> dict[str, float]:
    """
    portfolio: {"AAPL": 0.15, "QQQ": 0.25, ...}
    Returns normalized weights (sum to 1.0).
    """
    total = sum(portfolio.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in portfolio.items()}


def rebalance_trades(
    current_positions: dict[str, int],
    target_weights: dict[str, float],
    prices: dict[str, float],
    equity: float,
    drift_threshold: float = 0.05,
) -> list[dict]:
    """
    Returns list of {"action": "BUY"/"SELL", "ticker": "...", "shares": N}.
    Only generates trades where drift exceeds threshold (avoid churning).
    """
    trades = []
    total_market_val = sum(
        current_positions.get(t, 0) * prices.get(t, 0)
        for t in target_weights
    )
    portfolio_val = max(total_market_val, equity)   # use equity if portfolio is new

    for ticker, target_wt in target_weights.items():
        price = prices.get(ticker, 0.0)
        if price <= 0:
            continue
        current_shares = current_positions.get(ticker, 0)
        current_val    = current_shares * price
        current_wt     = current_val / portfolio_val if portfolio_val > 0 else 0

        drift = target_wt - current_wt
        if abs(drift) < drift_threshold:
            continue

        target_val    = portfolio_val * target_wt
        target_shares = int(target_val / price)
        delta         = target_shares - current_shares

        if delta == 0:
            continue

        trades.append({
            "action": "BUY" if delta > 0 else "SELL",
            "ticker": ticker,
            "shares": abs(delta),
            "price":  price,
            "drift":  drift,
        })
        log.info(
            f"[REBAL] {ticker}: wt {current_wt:.1%}→{target_wt:.1%}  "
            f"{'BUY' if delta > 0 else 'SELL'} {abs(delta)} shares @ {price:.2f}"
        )
    return trades


# ── IBKR execution ────────────────────────────────────────────────────────────

class LongTermPortfolio:
    """
    Manages a passive, long-term portfolio through IBKR.
    Call .rebalance() once per month (or run_monthly.py).
    """

    def __init__(self, broker, risk_mgr, portfolio_cfg: dict):
        """
        portfolio_cfg: {
            "positions": {"QQQ": 0.30, "SPY": 0.20, "AAPL": 0.10, ...},
            "drift_threshold": 0.05,
            "dca_dip_pct": 0.10,     # buy more if down >10% from 52w high
            "trailing_stop_pct": 0.20,  # exit if any position falls >20% from peak
            "max_equity_pct": 0.60,  # max fraction of account in long-term bucket
        }
        """
        self.broker   = broker
        self.risk_mgr = risk_mgr
        self.cfg      = portfolio_cfg
        self._peaks   = {}  # ticker → peak_price for trailing stop

    def status(self) -> pd.DataFrame:
        """Returns a DataFrame showing current vs target allocation."""
        weights  = compute_target_weights(self.cfg["positions"])
        tickers  = list(weights.keys())
        prices   = get_current_prices(tickers)
        equity   = self.broker.net_liquidation()
        current  = self.broker.positions()
        rows = []
        for t in tickers:
            p    = prices.get(t, 0)
            qty  = current.get(t, 0)
            val  = qty * p
            rows.append({
                "ticker":       t,
                "shares":       qty,
                "price":        round(p, 2),
                "market_val":   round(val, 2),
                "current_wt":   round(val / equity, 4) if equity > 0 else 0,
                "target_wt":    round(weights[t], 4),
            })
        return pd.DataFrame(rows)

    def rebalance(self, dry_run: bool = False) -> list[dict]:
        """
        Execute rebalancing trades.
        dry_run=True logs trades without placing them.
        """
        weights  = compute_target_weights(self.cfg["positions"])
        tickers  = list(weights.keys())
        prices   = get_current_prices(tickers)
        equity   = self.broker.net_liquidation() * self.cfg.get("max_equity_pct", 0.6)
        current  = self.broker.positions()

        trades = rebalance_trades(
            current, weights, prices, equity,
            drift_threshold=self.cfg.get("drift_threshold", 0.05)
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
        """Monitor long-term positions for trailing stop violations."""
        stop_pct = self.cfg.get("trailing_stop_pct", 0.20)
        positions = self.broker.positions()
        for ticker, qty in positions.items():
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
                drawdown = (peak - price) / peak
                if drawdown > stop_pct:
                    log.warning(
                        f"[LT_STOP] {ticker} drawdown {drawdown:.1%} > "
                        f"{stop_pct:.0%} → closing"
                    )
                    self.broker.market_order(ticker, qty, "SELL")
            except Exception as e:
                log.debug(f"[LT_STOP] {ticker}: {e}")

    def dca_dips(self):
        """
        Dollar-cost averaging: buy extra when price is N% below 52-week high.
        Only buys up to available allocation room.
        """
        dip_pct = self.cfg.get("dca_dip_pct", 0.10)
        weights = compute_target_weights(self.cfg["positions"])
        equity  = self.broker.net_liquidation()

        for ticker, weight in weights.items():
            try:
                hist = yf.Ticker(ticker).history(period="52wk")
                if hist.empty:
                    continue
                high_52w = hist["High"].max()
                last     = float(hist["Close"].iloc[-1])
                if high_52w <= 0:
                    continue
                dip = (high_52w - last) / high_52w
                if dip < dip_pct:
                    continue
                # buy a small extra tranche (half normal position)
                extra_val = equity * weight * 0.5
                shares    = int(extra_val / last)
                if shares <= 0:
                    continue
                if not self.risk_mgr.approve(ticker, shares, last):
                    continue
                log.info(f"[DCA] {ticker} is {dip:.1%} below 52w high → BUY {shares}")
                self.broker.market_order(ticker, shares, "BUY")
            except Exception as e:
                log.debug(f"[DCA] {ticker}: {e}")
