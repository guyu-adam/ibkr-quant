"""
OKX Crypto Perpetual Swap Trading System
────────────────────────────────────────
Usage:
    python -m crypto.main              # Demo / Mock mode
    python -m crypto.main --live       # Live trading (requires API keys)
    python -m crypto.main --status     # Account overview + signal scan

Setup:
    1. Copy crypto/.env.example → crypto/.env
    2. Fill in your OKX API Key / Secret / Passphrase
    3. Run: python -m crypto.main
"""

import sys
import os
import argparse
import logging
from datetime import datetime

# Ensure parent dir in path so we can import from both crypto/ and core/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crypto.config.settings import (
    SYMBOLS, LOG_LEVEL, LOG_DIR, DEMO,
    OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE,
)


def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s.%(msecs)03d %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(os.path.join(LOG_DIR, "crypto.log"), encoding="utf-8"),
        ],
    )
    return logging.getLogger("crypto")


def show_status(broker):
    """Print account summary and live ticker scan."""
    print()
    print("── OKX Account ─────────────────────────────")
    equity = broker.get_usdt_equity()
    print(f"  Equity:      ${equity:,.2f} USDT")
    positions = broker.get_positions()
    print(f"  Positions:   {len(positions)}")
    for instId, pos in positions.items():
        print(f"    {instId:<20} {float(pos.get('pos',0)):>8.0f} ct"
              f"  @ ${float(pos.get('avgPx',0)):,.2f}"
              f"  PnL=${float(pos.get('upl',0)):,.2f}")

    print()
    print("── Ticker Scan ─────────────────────────────")
    for sym in SYMBOLS:
        t = broker.get_ticker(sym)
        if t:
            print(f"  {sym:<20} last=${float(t.get('last',0)):,.2f}"
                  f"  bid=${float(t.get('bidPx',0)):,.2f}"
                  f"  ask=${float(t.get('askPx',0)):,.2f}")
        else:
            print(f"  {sym:<20} (unavailable)")

    # Quick signal scan if we have data
    print()
    print("── Quick Signal Scan ─────────────────────")
    try:
        from crypto.core.okx_data import OKXDataFeed
        from crypto.strategy.grid_scalp import GridScalpStrategy
        feed = OKXDataFeed(broker)
        strategy = GridScalpStrategy()
        for sym in SYMBOLS:
            df = feed.fetch_history(sym)
            if df is not None and len(df) > 20:
                sig = strategy.evaluate(df, sym, broker.get_positions())
                print(f"  {sym:<20} signal={sig['signal']:<5}"
                      f"  price={sig.get('price',0):<10}"
                      f"  RSI={sig.get('rsi',0):<6}"
                      f"  score={sig.get('score',0):<5}"
                      f"  {sig.get('reason','')}")
            else:
                print(f"  {sym:<20} (no data)")
    except Exception as e:
        print(f"  Signal scan failed: {e}")

    print()


def main():
    parser = argparse.ArgumentParser(
        description="OKX Crypto Perpetual Swap Trading",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m crypto.main              Demo/Mock mode (no API keys needed)
  python -m crypto.main --live       Live trading (needs API keys + YES confirm)
  python -m crypto.main --status     Account overview + signal scan
  python -m crypto.main --once       Evaluate signals once, print results
        """,
    )
    parser.add_argument("--live", action="store_true",
                        help="Live trading mode (flag=0, REAL orders)")
    parser.add_argument("--status", action="store_true",
                        help="Show account overview + ticker scan")
    parser.add_argument("--once", action="store_true",
                        help="Evaluate signals once and exit (no loop)")
    parser.add_argument("--mock", action="store_true",
                        help="Force MockBroker even if API keys are set")
    args = parser.parse_args()

    log = setup_logging()

    # ── Status mode: read-only ──────────────────────────────────────────────
    if args.status:
        log.info("Status mode — connecting read-only...")
        from crypto.core.mock_broker import MockBroker
        from crypto.core.okx_broker import OKXBroker

        has_keys = all([OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE])
        if has_keys and not args.mock:
            broker = OKXBroker(
                api_key=OKX_API_KEY, secret_key=OKX_SECRET_KEY,
                passphrase=OKX_PASSPHRASE, flag="1",
            )
            broker.connect()
        else:
            broker = MockBroker()
            broker.connect()

        show_status(broker)
        broker.disconnect()
        return

    # ── Once mode: single evaluation ────────────────────────────────────────
    if args.once:
        log.info("Once mode — single signal evaluation")
        from crypto.core.engine import create_engine
        engine = create_engine()
        engine.broker.connect()

        from crypto.config.settings import SIGNAL_COOLDOWN
        # Override cooldown so we always evaluate
        for instId in SYMBOLS:
            try:
                engine._process_symbol(instId)
            except Exception as e:
                log.error(f"{instId}: {e}")

        engine._check_grid_exits()
        engine.broker.disconnect()
        return

    # ── Trading mode ────────────────────────────────────────────────────────
    if not args.live:
        log.warning("═══ MOCK MODE — simulated trading, no real orders ═══")
        if any([OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE]):
            log.info("(API keys are set but --live not specified)")
    else:
        has_keys = all([OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE])
        if not has_keys:
            log.error("Cannot run --live without API keys. Set them in crypto/.env")
            sys.exit(1)

        print()
        print("╔══════════════════════════════════════════╗")
        print("║     ⚠ LIVE TRADING — REAL ORDERS ⚠     ║")
        print("╚══════════════════════════════════════════╝")
        print()
        confirm = input("Type 'YES' to confirm live trading: ").strip()
        if confirm != "YES":
            log.info("Aborted")
            return
        log.warning("═══ LIVE MODE — REAL orders will be placed ═══")

    from crypto.core.engine import create_engine
    engine = create_engine()

    # Override flag for live mode
    if args.live:
        from crypto.core.okx_broker import OKXBroker
        if hasattr(engine.broker, 'flag'):
            engine.broker.flag = "0"
        log.warning(f"Live mode: {datetime.now().isoformat()}")

    engine.start()


if __name__ == "__main__":
    main()
