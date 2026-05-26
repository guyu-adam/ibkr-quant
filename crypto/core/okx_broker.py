"""
OKX Broker — thin wrapper around python-okx SDK.
MarketAPI (public data), TradeAPI (orders), AccountAPI (balance/positions).

Usage:
    broker = OKXBroker(api_key, secret_key, passphrase, flag="1")
    broker.connect()
    ticker = broker.get_ticker("BTC-USDT-SWAP")
"""

from __future__ import annotations

import time
import logging
import functools
import pandas as pd

from crypto.config.settings import CT_VAL, LOT_SZ, MIN_SZ, OKX_DOMAIN

log = logging.getLogger(__name__)

RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 1.0


def _retry(func):
    """Exponential backoff retry on transient errors."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        last_err = None
        for attempt in range(RETRY_ATTEMPTS):
            try:
                return func(*args, **kwargs)
            except (ConnectionError, TimeoutError, OSError) as e:
                last_err = e
                if attempt < RETRY_ATTEMPTS - 1:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    log.warning(f"OKX call failed (attempt {attempt + 1}/{RETRY_ATTEMPTS}): {e}")
                    time.sleep(delay)
                else:
                    raise ConnectionError(
                        f"OKX call failed after {RETRY_ATTEMPTS} attempts: {last_err}")
        return None
    return wrapper


class OKXBroker:
    def __init__(self, api_key: str | None = None, secret_key: str | None = None,
                 passphrase: str | None = None, flag: str = "1",
                 domain: str = OKX_DOMAIN):
        self.flag = flag
        self._has_keys = all([api_key, secret_key, passphrase])
        self._instruments: dict[str, dict] = {}

        if not self._has_keys:
            log.warning("No API keys — broker in read-only mode (public endpoints only)")
            self._market = None
            self._trade = None
            self._account = None
            self._public = None
        else:
            try:
                import okx.MarketData as MarketData
                import okx.Trade as Trade
                import okx.Account as Account
                import okx.PublicData as PublicData

                self._market = MarketData.MarketAPI(
                    api_key=api_key, api_secret_key=secret_key,
                    passphrase=passphrase, flag=flag, domain=domain, debug=False)
                self._trade = Trade.TradeAPI(
                    api_key=api_key, api_secret_key=secret_key,
                    passphrase=passphrase, flag=flag, domain=domain, debug=False)
                self._account = Account.AccountAPI(
                    api_key=api_key, api_secret_key=secret_key,
                    passphrase=passphrase, flag=flag, domain=domain, debug=False)
                self._public = PublicData.PublicAPI(flag=flag, domain=domain, debug=False)
            except ImportError:
                log.warning("python-okx not installed — broker in read-only mode (pip install python-okx)")
                self._market = None
                self._trade = None
                self._account = None
                self._public = None

    # ── Connection ──────────────────────────────────────────────────────────
    def connect(self):
        if self._has_keys and self._market is not None:
            log.info(f"OKXBroker connected  flag={self.flag}  domain={OKX_DOMAIN}")
            self._fetch_instruments()
        elif not self._has_keys:
            log.warning("OKXBroker: no API keys, read-only mode (public endpoints)")
        else:
            log.warning("OKXBroker: python-okx not installed, read-only mode")

    def disconnect(self):
        log.info("OKXBroker disconnected")

    # ── Market data ─────────────────────────────────────────────────────────
    @_retry
    def get_ticker(self, instId: str) -> dict | None:
        if self._market is None:
            return None
        resp = self._market.get_ticker(instId=instId)
        if resp.get("code") == "0" and resp.get("data"):
            return resp["data"][0]
        log.error(f"get_ticker failed: {resp.get('msg', 'unknown')}")
        return None

    @_retry
    def get_candlesticks(self, instId: str, bar: str = "5m",
                         limit: int = 100) -> pd.DataFrame | None:
        if self._market is None:
            return None
        resp = self._market.get_candlesticks(instId=instId, bar=bar, limit=str(limit))
        if resp.get("code") != "0" or not resp.get("data"):
            log.error(f"get_candlesticks failed: {resp.get('msg', 'unknown')}")
            return None
        rows = []
        for d in resp["data"]:
            rows.append({
                "ts": pd.to_datetime(int(d[0])),
                "open": float(d[1]), "high": float(d[2]),
                "low": float(d[3]), "close": float(d[4]),
                "vol": float(d[5]), "volCcy": float(d[6]),
            })
        df = pd.DataFrame(rows)
        df.sort_values("ts", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df

    def last_price(self, instId: str) -> float:
        t = self.get_ticker(instId)
        if t and t.get("last"):
            return float(t["last"])
        return 0.0

    # ── Contract sizing ─────────────────────────────────────────────────────
    def contracts_from_usdt(self, instId: str, usdt_amount: float,
                            price: float) -> int:
        info = self._instruments.get(instId, {})
        ctVal = float(info.get("ctVal") or CT_VAL.get(instId, 0.01))
        lotSz = float(info.get("lotSz") or LOT_SZ.get(instId, 1))
        minSz = float(info.get("minSz") or MIN_SZ.get(instId, 1))
        if ctVal <= 0 or price <= 0:
            return 0
        raw = usdt_amount / price / ctVal
        lots = max(int(raw / lotSz) * int(lotSz), int(minSz))
        return lots

    @_retry
    def _fetch_instruments(self):
        if self._public is None:
            return
        resp = self._public.get_instruments(instType="SWAP")
        if resp.get("code") != "0":
            log.warning(f"Failed to fetch instruments: {resp.get('msg')}")
            return
        for inst in resp.get("data", []):
            if inst.get("state") == "live":
                self._instruments[inst["instId"]] = inst
        log.info(f"Fetched {len(self._instruments)} SWAP instruments")

    # ── Trading ─────────────────────────────────────────────────────────────
    @_retry
    def place_order(self, instId: str, side: str, sz: str,
                    ordType: str = "market", px: str | None = None) -> dict | None:
        if self._trade is None:
            log.warning("TradeAPI unavailable — order skipped")
            return None
        params = {
            "instId": instId, "tdMode": "cross",
            "side": side, "ordType": ordType, "sz": sz,
        }
        if px is not None:
            params["px"] = px
        resp = self._trade.place_order(**params)
        if resp.get("code") == "0":
            log.info(f"OKX {side.upper()} {sz} {instId} {ordType}"
                     f"{' @ ' + px if px else ''}")
            return resp["data"][0] if resp.get("data") else None
        log.error(f"place_order failed: {resp.get('msg', 'unknown')}")
        return None

    def market_buy(self, instId: str, sz: str) -> dict | None:
        return self.place_order(instId, "buy", sz)

    def market_sell(self, instId: str, sz: str) -> dict | None:
        return self.place_order(instId, "sell", sz)

    # ── Account ─────────────────────────────────────────────────────────────
    @_retry
    def get_balance(self) -> dict | None:
        if self._account is None:
            return None
        resp = self._account.get_account_balance()
        if resp.get("code") == "0" and resp.get("data"):
            return resp["data"][0]
        return None

    def get_usdt_equity(self) -> float:
        bal = self.get_balance()
        if bal and bal.get("totalEq"):
            return float(bal["totalEq"])
        return 0.0

    @_retry
    def get_positions(self) -> dict:
        if self._account is None:
            return {}
        resp = self._account.get_positions(instType="SWAP")
        if resp.get("code") != "0":
            return {}
        result = {}
        for pos in resp.get("data", []):
            qty = float(pos.get("pos", 0))
            if qty != 0:
                result[pos["instId"]] = {
                    "instId": pos["instId"],
                    "posSide": pos.get("posSide", "net"),
                    "pos": pos.get("pos", "0"),
                    "avgPx": pos.get("avgPx", "0"),
                    "upl": pos.get("upl", "0"),
                    "margin": pos.get("margin", ""),
                }
        return result

    def daily_pnl(self) -> float:
        total = 0.0
        for pos in self.get_positions().values():
            total += float(pos.get("upl", 0))
        return total
