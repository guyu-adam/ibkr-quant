"""
OKX — 欧易交易所适配器（永续合约）。

Usage:
    from interfaces.okx import OKXBroker
    broker = OKXBroker(api_key, secret_key, passphrase, flag="1")
    broker.connect()
    ticker = broker.get_ticker("BTC-USDT-SWAP")
"""

from __future__ import annotations

import time
import logging
import functools
import pandas as pd

from config.settings import OKX_DOMAIN

log = logging.getLogger(__name__)

RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 1.0


def _retry(func):
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
                    log.warning(f"OKX call failed ({attempt + 1}/{RETRY_ATTEMPTS}): {e}")
                    time.sleep(delay)
                else:
                    raise ConnectionError(
                        f"OKX call failed after {RETRY_ATTEMPTS} attempts: {last_err}")
        return None
    return wrapper


class OKXBroker:
    def __init__(self, api_key=None, secret_key=None, passphrase=None,
                 flag="1", domain=OKX_DOMAIN):
        self.flag = flag
        self._has_keys = all([api_key, secret_key, passphrase])
        self._instruments: dict[str, dict] = {}
        self._market = self._trade = self._account = self._public = None

        if self._has_keys:
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
                log.warning("python-okx not installed — read-only mode")

    def connect(self):
        if self._has_keys and self._market is not None:
            log.info(f"OKXBroker connected  flag={self.flag}")
            self._fetch_instruments()
        else:
            log.warning("OKXBroker: no API keys, read-only mode")

    def disconnect(self):
        log.info("OKXBroker disconnected")

    @_retry
    def get_ticker(self, instId: str) -> dict | None:
        if self._market is None:
            return None
        resp = self._market.get_ticker(instId=instId)
        return resp["data"][0] if resp.get("code") == "0" and resp.get("data") else None

    @_retry
    def get_candlesticks(self, instId: str, bar="5m", limit=100) -> pd.DataFrame | None:
        if self._market is None:
            return None
        resp = self._market.get_candlesticks(instId=instId, bar=bar, limit=str(limit))
        if resp.get("code") != "0" or not resp.get("data"):
            return None
        rows = [{"ts": pd.to_datetime(int(d[0])), "open": float(d[1]),
                 "high": float(d[2]), "low": float(d[3]),
                 "close": float(d[4]), "vol": float(d[5]),
                 "volCcy": float(d[6])} for d in resp["data"]]
        df = pd.DataFrame(rows)
        df.sort_values("ts", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df

    def last_price(self, instId: str) -> float:
        t = self.get_ticker(instId)
        return float(t["last"]) if t and t.get("last") else 0.0

    @_retry
    def place_order(self, instId: str, side: str, sz: str,
                    ordType="market", px=None) -> dict | None:
        if self._trade is None:
            log.warning("TradeAPI unavailable")
            return None
        params = {"instId": instId, "tdMode": "cross",
                  "side": side, "ordType": ordType, "sz": sz}
        if px is not None:
            params["px"] = px
        resp = self._trade.place_order(**params)
        if resp.get("code") == "0":
            log.info(f"OKX {side.upper()} {sz} {instId} {ordType}")
            return resp["data"][0] if resp.get("data") else None
        log.error(f"place_order failed: {resp.get('msg', 'unknown')}")
        return None

    def market_buy(self, instId, sz): return self.place_order(instId, "buy", sz)
    def market_sell(self, instId, sz): return self.place_order(instId, "sell", sz)

    @_retry
    def get_usdt_equity(self) -> float:
        if self._account is None:
            return 0.0
        resp = self._account.get_account_balance()
        if resp.get("code") == "0" and resp.get("data"):
            return float(resp["data"][0].get("totalEq", 0))
        return 0.0

    def net_liquidation(self): return self.get_usdt_equity()

    @_retry
    def get_positions(self) -> dict:
        if self._account is None:
            return {}
        resp = self._account.get_positions(instType="SWAP")
        if resp.get("code") != "0":
            return {}
        return {
            pos["instId"]: {
                "instId": pos["instId"], "posSide": pos.get("posSide", "net"),
                "pos": pos.get("pos", "0"), "avgPx": pos.get("avgPx", "0"),
                "upl": pos.get("upl", "0"), "margin": pos.get("margin", ""),
            }
            for pos in resp.get("data", []) if float(pos.get("pos", 0)) != 0
        }

    def positions(self): return self.get_positions()
    def daily_pnl(self): return sum(float(p.get("upl", 0)) for p in self.get_positions().values())

    @_retry
    def _fetch_instruments(self):
        if self._public is None:
            return
        resp = self._public.get_instruments(instType="SWAP")
        if resp.get("code") != "0":
            return
        for inst in resp.get("data", []):
            if inst.get("state") == "live":
                self._instruments[inst["instId"]] = inst
        log.info(f"Fetched {len(self._instruments)} SWAP instruments")
