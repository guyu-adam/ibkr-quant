"""
Monthly momentum rotation strategy.

Computes 3-month momentum scores for a universe of US equities and
generates buy/sell/hold orders to rotate into the top-N performers
each month.
"""

import logging
import pandas as pd
import numpy as np
import yfinance as yf
from typing import Optional

log = logging.getLogger(__name__)

# Universe of liquid, high-cap US equities to rotate through
UNIVERSE = [
    "SPY", "QQQ", "IWM", "DIA",
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META",
    "TSLA", "BRK-B", "JPM", "V", "JNJ", "WMT", "PG",
    "MA", "UNH", "HD", "DIS", "ADBE", "NFLX", "CRM",
    "AMD", "INTC", "QCOM", "TXN", "AVGO",
]

TOP_N = 5   # number of positions to hold at a time


def get_momentum_scores(
    universe: Optional[list[str]] = None,
    lookback_months: int = 3,
) -> pd.DataFrame:
    """
    Fetch price data for each symbol and rank by 3-month momentum.

    Returns DataFrame with columns:
        symbol, momentum, price, rank, selected
    """
    symbols = universe or UNIVERSE
    rows = []

    for sym in symbols:
        try:
            hist = yf.Ticker(sym).history(period=f"{lookback_months + 1}mo")
            if hist.empty or len(hist) < 20:
                continue
            start_px = float(hist["Close"].iloc[0])
            end_px = float(hist["Close"].iloc[-1])
            if start_px <= 0:
                continue
            momentum = (end_px - start_px) / start_px
            rows.append({
                "symbol":   sym,
                "momentum": round(momentum, 6),
                "price":    round(end_px, 2),
            })
        except Exception as e:
            log.debug(f"Momentum fetch failed for {sym}: {e}")
            continue

    if not rows:
        return pd.DataFrame(columns=["symbol", "momentum", "price", "rank", "selected"])

    df = pd.DataFrame(rows)
    df = df.sort_values("momentum", ascending=False).reset_index(drop=True)
    df["rank"] = range(1, len(df) + 1)
    df["rank"] = df["rank"].astype(int)
    df["selected"] = df["rank"] <= TOP_N
    return df


def generate_orders(
    scores: pd.DataFrame,
    current_holdings: dict[str, int],
    equity: float,
    top_n: int = TOP_N,
) -> dict:
    """
    Compute the trades needed to rotate into the top-N momentum symbols.

    Args:
        scores:           Output of get_momentum_scores()
        current_holdings: {symbol: shares} currently held
        equity:           Total portfolio value in USD
        top_n:            Number of positions to hold

    Returns:
        {
            "sell":   [{"symbol": ..., "shares": ..., "est_proceeds": ...}],
            "buy":    [{"symbol": ..., "shares": ..., "est_cost": ...}],
            "hold":   [{"symbol": ..., "shares": ...}],
            "target": [{"symbol": ..., "shares": ..., "price": ..., "weight": ...}],
        }
    """
    selected = scores[scores["selected"]].copy()
    n_selected = min(len(selected), top_n)

    if n_selected == 0:
        return {"sell": [], "buy": [], "hold": [], "target": []}

    # Equal-weight allocation
    weight_per = 1.0 / n_selected
    target_positions = {}

    for _, row in selected.head(n_selected).iterrows():
        sym = row["symbol"]
        px = row["price"]
        shares = int(equity * weight_per / px) if px > 0 else 0
        target_positions[sym] = {
            "symbol": sym,
            "shares": shares,
            "price": px,
            "weight": f"{weight_per:.0%}",
        }

    # Determine sells, buys, holds
    sells, buys, holds = [], [], []

    # Sell positions no longer in target
    for sym, qty in current_holdings.items():
        if sym not in target_positions and qty > 0:
            px = float(scores[scores["symbol"] == sym]["price"].iloc[0]) \
                if sym in scores["symbol"].values else 0.0
            sells.append({
                "symbol":       sym,
                "shares":       qty,
                "est_proceeds": round(qty * px, 2),
            })

    # Buy new target positions
    for sym, tgt in target_positions.items():
        current_qty = current_holdings.get(sym, 0)
        delta = tgt["shares"] - current_qty
        if delta > 0:
            buys.append({
                "symbol":    sym,
                "shares":    delta,
                "est_cost":  round(delta * tgt["price"], 2),
            })
        elif delta < 0:
            sells.append({
                "symbol":       sym,
                "shares":       abs(delta),
                "est_proceeds": round(abs(delta) * tgt["price"], 2),
            })
        else:
            holds.append({"symbol": sym, "shares": current_qty})

    return {
        "sell":   sells,
        "buy":    buys,
        "hold":   holds,
        "target": list(target_positions.values()),
    }
