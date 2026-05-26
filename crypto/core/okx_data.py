"""
OKX Data Feed — implements DataFeed interface from core/data_feed.py.
Bridges strategy layer with broker for data retrieval.
"""

from __future__ import annotations

import logging
import pandas as pd

from core.data_feed import DataFeed

log = logging.getLogger(__name__)

# Map interval strings to bar count for period estimation
_INTERVAL_MINUTES = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1H": 60, "2H": 120, "4H": 240,
}


class OKXDataFeed(DataFeed):
    def __init__(self, broker):
        self._broker = broker

    def name(self) -> str:
        return "okx_rest"

    def is_connected(self) -> bool:
        return True

    def fetch_history(self, symbol: str, period: str = "8h",
                      interval: str = "5m") -> pd.DataFrame | None:
        limit = self._period_to_limit(period, interval)
        return self._broker.get_candlesticks(symbol, bar=interval, limit=limit)

    def fetch_realtime(self, symbols: list[str]) -> dict[str, float]:
        result = {}
        for sym in symbols:
            ticker = self._broker.get_ticker(sym)
            if ticker and ticker.get("last"):
                result[sym] = float(ticker["last"])
        return result

    @staticmethod
    def _period_to_limit(period: str, interval: str) -> int:
        """Convert human-readable period to bar count."""
        mins = _INTERVAL_MINUTES.get(interval, 5)
        period_lower = period.lower()
        if "h" in period_lower:
            hours = int(period_lower.replace("h", "").strip())
            return (hours * 60) // mins
        if "d" in period_lower:
            days = int(period_lower.replace("d", "").strip())
            return (days * 24 * 60) // mins
        return max(50, int(period) if period.isdigit() else 100)
