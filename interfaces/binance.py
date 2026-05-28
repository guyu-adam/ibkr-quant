"""
币安 Binance — 现货 + 合约交易适配器 v2。

Usage:
    from interfaces.binance import BinanceBroker
    broker = BinanceBroker(api_key=..., secret=...)
    broker.connect()
    broker.market_order("BTCUSDT", 0.01, "BUY")
"""

import logging
import hashlib
import hmac
import time as _time
import urllib.parse

import pandas as pd
import requests

from core.broker_interface import BrokerInterface
from config.settings import BINANCE_API_KEY, BINANCE_SECRET

log = logging.getLogger(__name__)

BASE_URL = "https://api.binance.com"
TESTNET_BASE = "https://testnet.binance.vision"


class BinanceBroker(BrokerInterface):
    """Binance exchange adapter — spot & futures with authenticated access."""

    def __init__(self, api_key=BINANCE_API_KEY, secret=BINANCE_SECRET, testnet=False):
        self.api_key = api_key
        self.secret = secret
        self.testnet = testnet
        self._base = TESTNET_BASE if testnet else BASE_URL
        self._session = requests.Session()
        self._connected = False
        self._last_update = 0.0
        self._positions_cache: dict[str, float] = {}
        self._balances_cache: dict[str, float] = {}
        self._equity = 0.0

    # ── 签名 ────────────────────────────────────────────────────────────
    def _sign(self, params: dict) -> dict:
        params["timestamp"] = int(_time.time() * 1000)
        query = urllib.parse.urlencode(params)
        signature = hmac.new(
            self.secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        params["signature"] = signature
        return params

    def _signed_get(self, path: str, params: dict | None = None) -> dict:
        params = self._sign(params or {})
        headers = {"X-MBX-APIKEY": self.api_key}
        resp = self._session.get(
            f"{self._base}{path}", params=params, headers=headers, timeout=10
        )
        return resp.json() if resp.status_code == 200 else {}

    def _signed_post(self, path: str, params: dict | None = None) -> dict:
        params = self._sign(params or {})
        headers = {"X-MBX-APIKEY": self.api_key}
        resp = self._session.post(
            f"{self._base}{path}", data=params, headers=headers, timeout=10
        )
        return resp.json() if resp.status_code == 200 else {}

    # ── BrokerInterface ──────────────────────────────────────────────────
    def connect(self):
        if not self.api_key or not self.secret:
            log.warning("Binance: no API key — read-only mode for public endpoints")
        else:
            try:
                account = self._signed_get("/api/v3/account")
                if account and "balances" in account:
                    self._connected = True
                    self._refresh_balances(account)
                    log.info(f"Binance connected (testnet={self.testnet})")
                else:
                    log.warning("Binance: account info unavailable — check API keys")
            except Exception as e:
                log.error(f"Binance connect failed: {e}")

    def disconnect(self):
        self._connected = False
        log.info("Binance disconnected")

    def _refresh_balances(self, account: dict | None = None):
        if account is None:
            try:
                account = self._signed_get("/api/v3/account")
            except Exception:
                return

        if not account or "balances" not in account:
            return

        self._balances_cache = {
            b["asset"]: float(b["free"]) + float(b["locked"])
            for b in account["balances"]
            if float(b["free"]) + float(b["locked"]) > 0
        }
        self._last_update = _time.time()

    def _refresh_equity(self):
        """Calculate total equity in USDT using last prices."""
        if not self._balances_cache:
            self._refresh_balances()

        equity = 0.0
        for asset, amount in self._balances_cache.items():
            if asset in ("USDT", "BUSD", "USDC", "TUSD", "USDP", "DAI"):
                equity += amount
            else:
                symbol = f"{asset}USDT"
                px = self.last_price(symbol)
                if px > 0:
                    equity += amount * px
        self._equity = equity

    def net_liquidation(self) -> float:
        self._refresh_equity()
        return self._equity

    def daily_pnl(self) -> float:
        try:
            trades = self._signed_get("/api/v3/myTrades", {"limit": 50})
            pnl = 0.0
            today_start = int(pd.Timestamp.now().floor("D").timestamp() * 1000)
            for t in trades:
                if t.get("time", 0) >= today_start:
                    qty = abs(float(t.get("qty", 0)))
                    px = float(t.get("price", 0))
                    is_buy = t.get("isBuyer", False)
                    pnl += qty * px * (1 if not is_buy else -1)
            return pnl
        except Exception:
            return 0.0

    def positions(self) -> dict[str, float]:
        """Return {symbol: quantity} from spot balances (non-stablecoins treated as positions)."""
        self._refresh_balances()
        stable = {"USDT", "BUSD", "USDC", "TUSD", "USDP", "DAI"}
        return {
            k: v for k, v in self._balances_cache.items()
            if k not in stable and v > 0
        }

    def last_price(self, symbol: str) -> float:
        try:
            resp = self._session.get(
                f"{self._base}/api/v3/ticker/price",
                params={"symbol": symbol}, timeout=5,
            )
            data = resp.json()
            return float(data.get("price", 0))
        except Exception:
            return 0.0

    def get_klines(self, symbol: str, interval="5m", limit=100) -> pd.DataFrame | None:
        try:
            resp = self._session.get(
                f"{self._base}/api/v3/klines",
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
        if not self._connected:
            log.warning("Binance not connected — order skipped")
            return None
        side = action.upper()
        try:
            resp = self._signed_post("/api/v3/order", {
                "symbol": symbol, "side": side, "type": "MARKET",
                "quantity": abs(quantity),
            })
            if "orderId" in resp:
                log.info(f"Binance {side} {quantity} {symbol}  orderId={resp['orderId']}")
                return resp
            else:
                log.error(f"Binance order failed: {resp}")
                return None
        except Exception as e:
            log.error(f"Binance order failed: {e}")
            return None
