"""
交易引擎主循环
每隔 BAR_SIZE 拉取最新 K 线 → 计算信号 → 风控审批 → 下单
同时监控已有持仓的止损触发
"""

import time
import logging
from datetime import datetime, time as dtime
import pytz

from core.broker import IBKRBroker
from core.risk   import RiskManager
from strategy.signals import compute_indicators, generate_signal
from config.settings import (
    WATCHLIST, BAR_SIZE, MARKET_OPEN, MARKET_CLOSE,
    STOP_LOSS_ATR_MULT, SIGNAL_COOLDOWN,
    RSI_PERIOD, MOM_SLOW, ATR_PERIOD,
)

MIN_BARS = MOM_SLOW + ATR_PERIOD + 10  # need enough bars for slow EMA + ATR + buffer

log = logging.getLogger(__name__)
ET  = pytz.timezone("America/New_York")


def _market_time(t_str: str) -> dtime:
    h, m = map(int, t_str.split(":"))
    return dtime(h, m)


class TradingEngine:
    def __init__(self):
        self.broker  = IBKRBroker()
        self.risk    = RiskManager(self.broker)
        self._stops  = {}         # {symbol: stop_price}
        self._last_signal_time = {}   # 冷却计时

    # ── 生命周期 ─────────────────────────────────────────────────────────────
    def start(self):
        self.broker.connect()
        self.risk.reset_halt()
        log.info("Engine started")
        try:
            self._main_loop()
        finally:
            self._close_all_eod()
            self.broker.disconnect()
            log.info("Engine stopped")

    # ── 主循环 ───────────────────────────────────────────────────────────────
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
        # 冷却期检查
        last = self._last_signal_time.get(symbol, 0)
        if time.time() - last < SIGNAL_COOLDOWN:
            return

        df = self.broker.get_bars(symbol, duration="3 D", bar_size=BAR_SIZE)
        if df is None or len(df) < MIN_BARS:
            return

        df   = compute_indicators(df)
        sig  = generate_signal(df)

        positions = self.broker.positions()
        holding   = positions.get(symbol, 0)

        # ── 平仓逻辑 ─────────────────────────────────────────────────────────
        if holding > 0 and sig["signal"] == -1:
            log.info(f"[{symbol}] Close LONG  {sig['reason']}")
            self.broker.market_order(symbol, holding, "SELL")
            self._stops.pop(symbol, None)
            self._last_signal_time[symbol] = time.time()
            return

        if holding < 0 and sig["signal"] == 1:
            log.info(f"[{symbol}] Close SHORT  {sig['reason']}")
            self.broker.market_order(symbol, abs(holding), "BUY")
            self._stops.pop(symbol, None)
            self._last_signal_time[symbol] = time.time()
            return

        # ── 开仓逻辑 ─────────────────────────────────────────────────────────
        if holding == 0 and sig["signal"] != 0:
            shares = self.risk.position_size(sig["price"], sig["atr"])
            if shares <= 0:
                return
            if not self.risk.approve(symbol, shares, sig["price"]):
                return

            if sig["signal"] == 1:
                self.broker.market_order(symbol, shares, "BUY")
                self._stops[symbol] = sig["stop_long"]
                log.info(f"[{symbol}] OPEN LONG  {shares}sh @ {sig['price']:.2f}  stop={sig['stop_long']:.2f}  {sig['reason']}")
            else:
                self.broker.market_order(symbol, shares, "SELL")
                self._stops[symbol] = sig["stop_short"]
                log.info(f"[{symbol}] OPEN SHORT {shares}sh @ {sig['price']:.2f}  stop={sig['stop_short']:.2f}  {sig['reason']}")

            self._last_signal_time[symbol] = time.time()

    # ── 止损监控（每个周期检查）────────────────────────────────────────────────
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

    # ── 收盘前全部平仓 ────────────────────────────────────────────────────────
    def _close_all_eod(self):
        for symbol, qty in self.broker.positions().items():
            if qty == 0:
                continue
            action = "SELL" if qty > 0 else "BUY"
            log.info(f"[EOD] Closing {symbol}  qty={qty}")
            self.broker.market_order(symbol, abs(qty), action)

    # ── 工具 ─────────────────────────────────────────────────────────────────
    @staticmethod
    def _is_market_open(t: dtime) -> bool:
        return _market_time(MARKET_OPEN) <= t <= _market_time(MARKET_CLOSE)

    @staticmethod
    def _bar_to_seconds(bar_size: str) -> int:
        n, unit = bar_size.split()
        n = int(n)
        return n * (60 if "min" in unit else 3600 if "hour" in unit else 1)
