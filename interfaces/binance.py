"""
币安 Binance — 现货 + 合约交易适配器。

Usage:
    from interfaces.binance import BinanceBroker
    broker = BinanceBroker(api_key=..., secret=...)
    broker.connect()
    broker.market_order("BTCUSDT", 0.01, "BUY")
"""

import logging
import pandas as pd

from config.settings import BINANCE_API_KEY, BINANCE_SECRET

log = logging.getLogger(__name__)


class BinanceBroker:
    """Binance exchange adapter — spot & futures."""

    def __init__(self, api_key=BINANCE_API_KEY, secret=BINANCE_SECRET, testnet=False):
        self.api_key = api_key
        self.secret = secret
        self.testnet = testnet
        self._spot = None
        self._futures = None
        self._connected = False

    def connect(self):
        if not self.api_key:
            log.warning("Binance: no API key configured — read-only mode")
            return
        try:
            from binance.spot import Spot
            self._spot = Spot(
                api_key=self.api_key, api_secret=self.secret,
                base_url="https://testnet.binance.vision" if self.testnet
                else "https://api.binance.com",
            )
            self._connected = True
            log.info(f"Binance connected (testnet={self.testnet})")
        except ImportError:
            log.warning("binance-connector not installed — read-only mode")
        except Exception as e:
            log.error(f"Binance connect failed: {e}")

    def disconnect(self):
        self._connected = False
        log.info("Binance disconnected")

    def last_price(self, symbol: str) -> float:
        """Get last price via public endpoint (no auth needed)."""
        try:
            import requests
            resp = requests.get(
                "https://api.binance.com/api/v3/ticker/price",
                params={"symbol": symbol}, timeout=5,
            )
            return float(resp.json()["price"])
        except Exception:
            return 0.0

    def get_klines(self, symbol: str, interval="5m", limit=100) -> pd.DataFrame | None:
        try:
            import requests
            resp = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": symbol, "interval": interval, "limit": limit},
                timeout=10,
            )
            data = resp.json()
            df = pd.DataFrame(data, columns=[
                "ts", "open", "high", "low", "close", "volume",
                "close_time", "quote_vol", "trades", "taker_buy_vol",
                "taker_buy_quote_vol", "ignore",
            ])
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = df[col].astype(float)
            df["ts"] = pd.to_datetime(df["ts"], unit="ms")
            return df[["ts", "open", "high", "low", "close", "volume"]]
        except Exception as e:
            log.error(f"Binance klines failed: {e}")
            return None

    def market_order(self, symbol: str, quantity: float, action: str):
        if self._spot is None:
            log.warning("Binance Spot not connected — order skipped")
            return None
        side = action.upper()
        try:
            resp = self._spot.new_order(
                symbol=symbol, side=side, type="MARKET", quantity=quantity,
            )
            log.info(f"Binance {side} {quantity} {symbol}")
            return resp
        except Exception as e:
            log.error(f"Binance order failed: {e}")
            return None

    def net_liquidation(self) -> float:
        return 0.0

    def daily_pnl(self) -> float:
        return 0.0

    def positions(self) -> dict:
        return {}
