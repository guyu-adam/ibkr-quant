"""
嘉信 Charles Schwab — 美股/ETF 交易适配器。

Schwab uses OAuth 2.0 for API access. Setup:
  1. Register app at developer.schwab.com
  2. Get API Key + Secret
  3. First run will prompt for OAuth authorization

Usage:
    from interfaces.schwab import SchwabBroker
    broker = SchwabBroker(api_key=..., secret=..., callback_url=...)
    broker.connect()
    broker.market_order("AAPL", 10, "BUY")
"""

import logging
from config.settings import SCHWAB_API_KEY, SCHWAB_SECRET, SCHWAB_CALLBACK

log = logging.getLogger(__name__)


class SchwabBroker:
    """Charles Schwab API adapter (OAuth 2.0)."""

    def __init__(self, api_key=SCHWAB_API_KEY, secret=SCHWAB_SECRET,
                 callback=SCHWAB_CALLBACK):
        self.api_key = api_key
        self.secret = secret
        self.callback = callback
        self._token = None
        self._connected = False

    def connect(self):
        if not self.api_key:
            log.warning("Schwab: no API key configured — read-only mode")
            return
        # TODO: Implement OAuth 2.0 flow
        # 1. Redirect to Schwab auth URL
        # 2. Get authorization code from callback
        # 3. Exchange code for access token
        # 4. Refresh token as needed
        self._connected = True
        log.info("Schwab connected (stub)")

    def disconnect(self):
        self._connected = False
        log.info("Schwab disconnected")

    def net_liquidation(self) -> float:
        return 0.0

    def daily_pnl(self) -> float:
        return 0.0

    def positions(self) -> dict:
        return {}

    def last_price(self, symbol: str) -> float:
        return 0.0

    def market_order(self, symbol: str, shares: int, action: str):
        log.warning(f"Schwab: market_order not yet implemented ({action} {shares} {symbol})")
