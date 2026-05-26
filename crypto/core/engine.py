"""
Crypto Trading Engine — main trading loop.
Follows the core/engine.py pattern: connect → while-loop → process → sleep.
Auto-detects MockBroker vs OKXBroker based on available API keys.
"""

import time
import logging
import signal
import sys
from datetime import datetime

import pandas as pd

from crypto.config.settings import (
    SYMBOLS, SIGNAL_COOLDOWN, LOOP_SLEEP, BAR_INTERVAL, CANDLE_LIMIT,
    OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE,
)

log = logging.getLogger(__name__)


class CryptoEngine:
    def __init__(self, broker, risk, strategy, data_feed):
        self.broker    = broker
        self.risk      = risk
        self.strategy  = strategy
        self.feed      = data_feed
        self._cooldown: dict[str, float] = {}
        self._running  = True
        self._bar_count = 0
        self._start_time = time.time()

        # Register graceful shutdown
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    def _handle_shutdown(self, signum, frame):
        log.info("Shutdown signal received — closing positions gracefully...")
        self._running = False

    # ── Lifecycle ───────────────────────────────────────────────────────────
    def start(self):
        self.broker.connect()
        self.risk.reset_halt()

        is_mock = "mock" in type(self.broker).__name__.lower()
        mode = "MOCK" if is_mock else ("DEMO" if self.broker.flag == "1" else "LIVE")
        log.info(f"CryptoEngine started  mode={mode}  symbols={SYMBOLS}  "
                 f"sleep={LOOP_SLEEP}s  bar={BAR_INTERVAL}")

        try:
            self._main_loop()
        except KeyboardInterrupt:
            log.info("KeyboardInterrupt — shutting down")
        finally:
            self._close_all_positions()
            self.broker.disconnect()
            self._print_summary()
            log.info("CryptoEngine stopped")

    # ── Main loop ───────────────────────────────────────────────────────────
    def _main_loop(self):
        while self._running:
            loop_start = time.time()

            for instId in SYMBOLS:
                try:
                    self._process_symbol(instId)
                except Exception as e:
                    log.error(f"{instId}: {e}", exc_info=True)

            # Check grid exits (TP/SL) every loop
            self._check_grid_exits()

            self._bar_count += 1

            # Periodic status log every 30 loops (~5 min)
            if self._bar_count % 30 == 0:
                self._status_log()

            # Sleep, accounting for processing time
            elapsed = time.time() - loop_start
            sleep_for = max(0.5, LOOP_SLEEP - elapsed)
            time.sleep(sleep_for)

    def _process_symbol(self, instId: str):
        # Cooldown check
        now = time.time()
        last = self._cooldown.get(instId, 0)
        if now - last < SIGNAL_COOLDOWN:
            return

        # Fetch data
        df = self.broker.get_candlesticks(instId, bar=BAR_INTERVAL, limit=CANDLE_LIMIT)
        if df is None or len(df) < 20:
            return

        # Get current positions
        positions = self.broker.get_positions()

        # Evaluate signal
        result = self.strategy.evaluate(df, instId, positions)
        signal = result.get("signal", "hold")
        price = result.get("price", 0)
        score = result.get("score", 0)

        if signal == "hold" or price <= 0:
            return

        # ── SELL: close position ────────────────────────────────────────────
        if signal == "sell":
            pos = positions.get(instId)
            active_entries = self.strategy.get_grid_entries(instId)

            if pos and float(pos.get("pos", 0)) > 0:
                qty = int(float(pos["pos"]))
                log.info(f"[{instId}] CLOSE LONG  qty={qty}  @ {price:.2f}  "
                         f"score={score:.1f}  {result['reason']}")
                self.broker.market_sell(instId, str(qty))
                self._cooldown[instId] = now

                # Clear grid entries for this symbol
                for entry in list(active_entries):
                    self.strategy.remove_grid_entry(instId, entry)

            elif active_entries:
                log.info(f"[{instId}] Signal SELL but no exchange position "
                         f"(grid entries={len(active_entries)}). Checking TP/SL first.")
            return

        # ── BUY: open new position ──────────────────────────────────────────
        if signal == "buy":
            sz = self.risk.position_size(instId, price)
            if sz <= 0:
                log.debug(f"[{instId}] position_size=0, skipping")
                return

            if not self.risk.approve(instId, sz, price):
                log.info(f"[{instId}] Risk rejected BUY {sz} @ {price:.2f}")
                return

            log.info(f"[{instId}] OPEN LONG  "
                     f"sz={sz}  @ {price:.2f}  score={score:.1f}  "
                     f"RSI={result.get('rsi','?')}  {result['reason']}")

            trade = self.broker.market_buy(instId, str(sz))
            if trade:
                self.strategy.add_grid_entry(instId, sz, price)
                self._cooldown[instId] = now

    # ── Grid stop-loss / take-profit monitoring ─────────────────────────────
    def _check_grid_exits(self):
        for instId in list(SYMBOLS):
            entries = self.strategy.get_grid_entries(instId)
            if not entries:
                continue

            price = self.broker.last_price(instId)
            if price <= 0:
                continue

            for entry in list(entries):
                hit = None
                if price >= entry.tp_price:
                    hit = "TP"
                elif price <= entry.sl_price:
                    hit = "SL"

                if hit:
                    log.info(f"[{instId}] Grid {hit}  "
                             f"sz={entry.sz}  entry={entry.entry_price:.2f}  "
                             f"current={price:.2f}  "
                             f"target={entry.tp_price:.2f}/{entry.sl_price:.2f}")
                    self.broker.market_sell(instId, str(entry.sz))
                    self.strategy.remove_grid_entry(instId, entry)

    # ── Emergency close all ─────────────────────────────────────────────────
    def _close_all_positions(self):
        positions = self.broker.get_positions()
        if not positions:
            log.info("No open positions to close")
            return

        log.warning(f"Emergency close {len(positions)} positions")
        for instId, pos in positions.items():
            qty = abs(int(float(pos.get("pos", 0))))
            if qty <= 0:
                continue
            side = "sell" if float(pos.get("pos", 0)) > 0 else "buy"
            self.broker.place_order(instId, side, str(qty))
            log.info(f"[EMERGENCY] {side.upper()} {qty} {instId}")

    # ── Status ──────────────────────────────────────────────────────────────
    def _status_log(self):
        equity = self.broker.get_usdt_equity()
        positions = self.broker.get_positions()
        grid_total = self.strategy.grid_count()
        elapsed = time.time() - self._start_time
        log.info(f"── STATUS {datetime.now().strftime('%H:%M:%S')} "
                 f"loops={self._bar_count} uptime={elapsed/60:.0f}m "
                 f"equity={equity:.2f} positions={len(positions)} grid={grid_total} ──")

    def _print_summary(self):
        elapsed = time.time() - self._start_time
        equity = self.broker.get_usdt_equity()
        log.info(f"─── Session Summary ───")
        log.info(f"  Duration:    {elapsed/60:.1f} min")
        log.info(f"  Loops:       {self._bar_count}")
        log.info(f"  Final equity:{equity:.2f} USDT")


def create_engine():
    """Factory: auto-select MockBroker or OKXBroker based on API key availability."""
    from crypto.core.mock_broker import MockBroker
    from crypto.core.okx_broker import OKXBroker
    from crypto.core.okx_data import OKXDataFeed
    from crypto.core.risk import CryptoRiskManager
    from crypto.strategy.grid_scalp import GridScalpStrategy

    has_keys = all([OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE])

    if has_keys:
        log.info("API keys found → using OKXBroker")
        broker = OKXBroker(
            api_key=OKX_API_KEY, secret_key=OKX_SECRET_KEY,
            passphrase=OKX_PASSPHRASE, flag="1",
        )
    else:
        log.info("No API keys → using MockBroker (simulated trading)")
        broker = MockBroker()

    data_feed  = OKXDataFeed(broker)
    risk       = CryptoRiskManager(broker)
    strategy   = GridScalpStrategy()
    engine     = CryptoEngine(broker, risk, strategy, data_feed)
    return engine
