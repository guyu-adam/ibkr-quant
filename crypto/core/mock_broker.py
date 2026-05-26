"""
Mock OKX Broker — used when no API keys are configured.
Simulates trading with virtual account and random-walk price generation.
Same interface as OKXBroker so the engine works identically.
"""

from __future__ import annotations

import math
import time
import random
import logging
from collections import defaultdict

import numpy as np
import pandas as pd

from crypto.config.settings import SYMBOLS, CT_VAL, LOT_SZ, MIN_SZ, ACCOUNT_EQUITY

log = logging.getLogger(__name__)


class MockBroker:
    """In-memory simulated broker for testing without real API keys."""

    def __init__(self):
        self._equity = float(ACCOUNT_EQUITY)
        self._cash = float(ACCOUNT_EQUITY)
        self._positions: dict[str, dict] = {}  # {instId: {qty, avgPx, side}}
        self._prices: dict[str, float] = {}     # current simulated prices
        self._daily_pnl = 0.0
        self._start_equity = float(ACCOUNT_EQUITY)
        self._rng = random.Random(42)
        self._trades: list[dict] = []

        # Initialize prices for each symbol
        _base_prices = {
            "BTC-USDT-SWAP": 68000.0,
            "ETH-USDT-SWAP": 3500.0,
            "SOL-USDT-SWAP": 180.0,
        }
        for sym in SYMBOLS:
            self._prices[sym] = _base_prices.get(sym, 100.0)
        self._history: dict[str, list[dict]] = {s: [] for s in SYMBOLS}

    # ── Connection (no-op) ──────────────────────────────────────────────────
    def connect(self):
        log.info("MockBroker connected (simulated trading)")

    def disconnect(self):
        log.info("MockBroker disconnected")

    # ── Market data ─────────────────────────────────────────────────────────
    def get_ticker(self, instId: str) -> dict:
        self._tick_price(instId)
        price = self._prices[instId]
        spread = price * 0.0001
        return {
            "instId": instId,
            "last": str(price),
            "bidPx": str(round(price - spread, 2)),
            "askPx": str(round(price + spread, 2)),
            "high24h": str(round(price * 1.02, 2)),
            "low24h": str(round(price * 0.98, 2)),
            "vol24h": str(round(random.uniform(1000, 5000), 2)),
        }

    def get_candlesticks(self, instId: str, bar: str = "5m", limit: int = 100) -> pd.DataFrame:
        self._generate_history(instId, limit)
        rows = self._history[instId][-limit:]
        df = pd.DataFrame(rows)
        df["ts"] = pd.to_datetime(df["ts"])
        return df

    def last_price(self, instId: str) -> float:
        self._tick_price(instId)
        return self._prices[instId]

    # ── Contract sizing (same logic as OKXBroker) ──────────────────────────
    def contracts_from_usdt(self, instId: str, usdt_amount: float, price: float) -> int:
        ctVal = CT_VAL.get(instId, 0.01)
        lotSz = LOT_SZ.get(instId, 1)
        minSz = MIN_SZ.get(instId, 1)
        if ctVal <= 0 or price <= 0:
            return 0
        raw = usdt_amount / price / ctVal
        lots = max(int(raw / lotSz) * lotSz, minSz)
        return int(lots)

    # ── Trading ─────────────────────────────────────────────────────────────
    def place_order(self, instId: str, side: str, sz: str,
                    ordType: str = "market", px: str | None = None) -> dict | None:
        qty = int(sz)
        price = self.last_price(instId)
        ctVal = CT_VAL.get(instId, 0.01)
        notional = qty * price * ctVal

        if side == "buy":
            pos_key = f"{instId}_long"
            if self._cash < notional:
                log.warning(f"[MOCK] Insufficient cash for BUY {qty} {instId}")
                return None
            self._cash -= notional
            if pos_key in self._positions:
                old = self._positions[pos_key]
                total_qty = old["qty"] + qty
                old["avgPx"] = (old["avgPx"] * old["qty"] + price * qty) / total_qty
                old["qty"] = total_qty
            else:
                self._positions[pos_key] = {"qty": qty, "avgPx": price, "side": "long"}
        else:
            pos_key = f"{instId}_long"
            if pos_key in self._positions:
                old = self._positions[pos_key]
                close_qty = min(qty, old["qty"])
                pnl = (price - old["avgPx"]) * close_qty * ctVal
                self._cash += close_qty * price * ctVal
                self._daily_pnl += pnl
                old["qty"] -= close_qty
                if old["qty"] <= 0:
                    del self._positions[pos_key]
            else:
                log.warning(f"[MOCK] No long position to sell for {instId}")
                return None

        trade = {"instId": instId, "side": side, "sz": qty, "px": price,
                 "ordId": f"mock_{int(time.time()*1000)}", "sCode": "0"}
        self._trades.append(trade)
        log.info(f"[MOCK] {side.upper()} {qty} {instId} @ {price:.2f}")
        return trade

    def market_buy(self, instId: str, sz: str) -> dict | None:
        return self.place_order(instId, "buy", sz)

    def market_sell(self, instId: str, sz: str) -> dict | None:
        return self.place_order(instId, "sell", sz)

    # ── Account ─────────────────────────────────────────────────────────────
    def get_balance(self) -> dict:
        return {"totalEq": str(self._equity), "availBal": str(self._cash)}

    def get_usdt_equity(self) -> float:
        pos_value = 0.0
        for pos_key, pos in self._positions.items():
            instId = pos_key.replace("_long", "")
            price = self._prices.get(instId, 0)
            ctVal = CT_VAL.get(instId, 0.01)
            pos_value += pos["qty"] * price * ctVal
        self._equity = self._cash + pos_value
        return self._equity

    def get_positions(self) -> dict:
        result = {}
        for pos_key, pos in self._positions.items():
            if pos["qty"] > 0:
                instId = pos_key.replace("_long", "")
                price = self._prices.get(instId, 0)
                ctVal = CT_VAL.get(instId, 0.01)
                upl = (price - pos["avgPx"]) * pos["qty"] * ctVal
                result[instId] = {
                    "instId": instId,
                    "posSide": "long",
                    "pos": str(pos["qty"]),
                    "avgPx": str(pos["avgPx"]),
                    "upl": str(round(upl, 4)),
                    "margin": "",
                }
        return result

    def daily_pnl(self) -> float:
        return self._daily_pnl + self._unrealized_pnl()

    # ── Price simulation (random walk with mean reversion) ──────────────────
    def _tick_price(self, instId: str):
        vols = {"BTC-USDT-SWAP": 0.002, "ETH-USDT-SWAP": 0.003, "SOL-USDT-SWAP": 0.006}
        base = {"BTC-USDT-SWAP": 68000.0, "ETH-USDT-SWAP": 3500.0, "SOL-USDT-SWAP": 180.0}
        vol = vols.get(instId, 0.003)
        center = base.get(instId, 100.0)

        cur = self._prices.get(instId, center)
        # Random walk with mean reversion pull
        shock = self._rng.gauss(0, vol * cur)
        reversion = (center - cur) * 0.001
        cur = cur + shock + reversion
        cur = max(cur, center * 0.7)
        cur = min(cur, center * 1.3)
        self._prices[instId] = cur

        # Record for history
        ts = int(time.time() * 1000)
        self._history.setdefault(instId, []).append({
            "ts": ts, "open": cur, "high": cur * 1.001, "low": cur * 0.999,
            "close": cur, "vol": random.uniform(100, 500),
            "volCcy": random.uniform(500000, 2000000),
        })
        # Keep history bounded
        if len(self._history[instId]) > 500:
            self._history[instId] = self._history[instId][-500:]

    def _generate_history(self, instId: str, count: int):
        vols = {"BTC-USDT-SWAP": 200.0, "ETH-USDT-SWAP": 8.0, "SOL-USDT-SWAP": 1.2}
        base = {"BTC-USDT-SWAP": 68000.0, "ETH-USDT-SWAP": 3500.0, "SOL-USDT-SWAP": 180.0}
        vol = vols.get(instId, 5.0)
        center = base.get(instId, 100.0)

        if len(self._history.get(instId, [])) >= count:
            return

        rng = random.Random(hash(instId) + 42)
        price = center
        bars = []
        for i in range(count):
            ts = int((time.time() - (count - i) * 300) * 1000)
            o = price
            c = price + rng.gauss(0, vol)
            c = max(c, center * 0.7)
            c = min(c, center * 1.3)
            h = max(o, c) * (1 + abs(rng.gauss(0, 0.001)))
            l = min(o, c) * (1 - abs(rng.gauss(0, 0.001)))
            v = abs(rng.gauss(300, 100))
            bars.append({"ts": ts, "open": o, "high": h, "low": l, "close": c,
                         "vol": v, "volCcy": v * c})
            price = c
        self._history[instId] = bars

    def _unrealized_pnl(self) -> float:
        total = 0.0
        for pos_key, pos in self._positions.items():
            if pos["qty"] > 0:
                instId = pos_key.replace("_long", "")
                price = self._prices.get(instId, 0)
                ctVal = CT_VAL.get(instId, 0.01)
                total += (price - pos["avgPx"]) * pos["qty"] * ctVal
        return total
