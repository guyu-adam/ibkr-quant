"""
交易引擎主循环 v3 — 每周期拉取K线 → 策略评估 → 风控审批 → 下单。
同时监控已有持仓的止损触发。
"""

import time
import logging
from datetime import datetime, time as dtime
import pytz

from interfaces.ibkr import IBKRBroker
from core.risk import RiskManager
from strategies.fast_trading import MeanReversionStrategy
from config.settings import (
    WATCHLIST, BAR_SIZE, MARKET_OPEN, MARKET_CLOSE,
    SIGNAL_COOLDOWN,
)

MIN_BARS = 60

log = logging.getLogger(__name__)
ET = pytz.timezone("America/New_York")


def _market_time(t_str: str) -> dtime:
    h, m = map(int, t_str.split(":"))
    return dtime(h, m)


class TradingEngine:
    def __init__(self):
        self.broker = IBKRBroker()
        self.risk = RiskManager(self.broker)
        self.strategy = MeanReversionStrategy()
        self._stops: dict[str, float] = {}
        self._last_signal_time: dict[str, float] = {}

    # ── 生命周期 ─────────────────────────────────────────────────────────
    def start(self):
        self.broker.connect()
        self.risk.reset_halt()
        self.strategy.start()
        log.info("Engine started")
        try:
            self._main_loop()
        finally:
            self._close_all_eod()
            self.strategy.stop()
            self.broker.disconnect()
            log.info("Engine stopped")

    # ── 主循环 ───────────────────────────────────────────────────────────
    def _main_loop(self):
        bar_seconds = self._bar_to_seconds(BAR_SIZE)
        while True:
            now_et = datetime.now(ET).time()
            if not self._is_market_open(now_et):
                log.info(f"Market closed ({now_et})  sleeping 60s")
                time.sleep(60)
                continue

            for symbol in WATCHLIST:
                try:
                    self._process_symbol(symbol)
                except Exception as e:
                    log.error(f"{symbol}: {e}")

            self._check_stops()
            time.sleep(bar_seconds)

    def _process_symbol(self, symbol: str):
        last = self._last_signal_time.get(symbol, 0)
        if time.time() - last < SIGNAL_COOLDOWN:
            return

        positions = self.broker.positions()
        holding = positions.get(symbol, 0)

        result = self.strategy.evaluate(
            type("Feed", (), {
                "fetch_history": lambda s, p="6mo", iv="1d":
                    self.broker.get_bars(s, duration="3 D", bar_size=BAR_SIZE)
            })(),
            symbol,
            positions={symbol: {"avg_cost": 0, "stop_loss": self._stops.get(symbol, 0)}}
            if holding else None,
        )

        price = result.get("close", 0)
        if price <= 0:
            return

        # ── 平仓 ─────────────────────────────────────────────────────────
        if holding != 0 and result["signal"] in ("sell",):
            action = "SELL" if holding > 0 else "BUY"
            log.info(f"[{symbol}] Close  {result['reason']}")
            self.broker.market_order(symbol, abs(holding), action)
            self._stops.pop(symbol, None)
            self._last_signal_time[symbol] = time.time()
            return

        # ── 开仓 ─────────────────────────────────────────────────────────
        if holding == 0 and result["signal"] == "buy":
            atr_val = result.get("atr", price * 0.02)
            shares = self.risk.position_size(price, atr_val)
            if shares <= 0:
                return
            if not self.risk.approve(symbol, shares, price):
                return

            self.broker.market_order(symbol, shares, "BUY")
            stop_mult = self.risk.get_atr_multiplier()
            self._stops[symbol] = price - stop_mult * atr_val
            log.info(f"[{symbol}] OPEN LONG  {shares}sh @ {price:.2f}  "
                     f"stop={self._stops[symbol]:.2f}  {result['reason']}")
            self._last_signal_time[symbol] = time.time()

    # ── 止损监控 ─────────────────────────────────────────────────────────
    def _check_stops(self):
        positions = self.broker.positions()
        for symbol, stop_price in list(self._stops.items()):
            qty = positions.get(symbol, 0)
            if qty == 0:
                self._stops.pop(symbol, None)
                continue
            price = self.broker.last_price(symbol)
            if price <= 0:
                continue
            if (qty > 0 and price <= stop_price) or (qty < 0 and price >= stop_price):
                action = "SELL" if qty > 0 else "BUY"
                log.warning(f"[{symbol}] STOP HIT  price={price:.2f}  stop={stop_price:.2f}")
                self.broker.market_order(symbol, abs(qty), action)
                self._stops.pop(symbol, None)

    # ── 收盘全平 ─────────────────────────────────────────────────────────
    def _close_all_eod(self):
        for symbol, qty in self.broker.positions().items():
            if qty == 0:
                continue
            action = "SELL" if qty > 0 else "BUY"
            log.info(f"[EOD] Closing {symbol}  qty={qty}")
            try:
                self.broker.market_order(symbol, abs(qty), action)
            except Exception as e:
                log.error(f"[EOD] {symbol}: {e}")

    # ── 工具 ─────────────────────────────────────────────────────────────
    @staticmethod
    def _is_market_open(t: dtime) -> bool:
        return _market_time(MARKET_OPEN) <= t <= _market_time(MARKET_CLOSE)

    @staticmethod
    def _bar_to_seconds(bar_size: str) -> int:
        n, unit = bar_size.split()
        n = int(n)
        return n * (60 if "min" in unit else 3600 if "hour" in unit else 1)
