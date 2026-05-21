"""
IBKR Multi-Strategy Trading System
────────────────────────────────────
Strategies running concurrently:
  1. US Momentum (intraday, RSI + EMA crossover)
  2. HK IPO First-Day Pop (runs at HK open)
  3. Timezone Arbitrage HK←→US ADR (runs at HK open, pre-computed overnight)
  4. Long-Term Portfolio (monthly rebalance, trailing stop monitoring)

Usage:
  python main.py            # live/paper trading
  python main.py --backtest # offline backtest (US momentum only)
  python main.py --status   # show current positions + PnL
  python main.py --rebalance # force long-term rebalance now

Prerequisites:
  1. IBKR TWS or Gateway running
  2. API enabled: TWS → Edit → Global Config → API → Settings → Enable Socket
  3. pip install ib_insync yfinance schedule beautifulsoup4 lxml
  4. PAPER_TRADE = True in config/settings.py (until you're confident)
"""

import logging
import sys
import os
import argparse
import time
import threading
from datetime import datetime

import schedule
import pytz

sys.path.insert(0, os.path.dirname(__file__))

from core.broker    import IBKRBroker
from core.engine    import TradingEngine
from core.risk      import RiskManager
from strategy.hk_ipo    import HKIPOStrategy
from strategy.tz_arb    import TZArbStrategy
from strategy.long_term import LongTermPortfolio
from config.settings import (
    PAPER_TRADE, TZ_ARB, HK_IPO, LONG_TERM_PORTFOLIO,
)

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/trading.log"),
    ],
)
log = logging.getLogger(__name__)

ET  = pytz.timezone("America/New_York")
HKT = pytz.timezone("Asia/Hong_Kong")


def now_et():  return datetime.now(ET)
def now_hkt(): return datetime.now(HKT)


def show_status(broker: IBKRBroker):
    print("\n── Account ──────────────────────────────────")
    try:
        nlv = broker.net_liquidation()
        pnl = broker.daily_pnl()
        pos = broker.positions()
        print(f"  Net Liquidation:  ${nlv:,.2f}")
        print(f"  Daily P&L:        ${pnl:,.2f}  ({pnl/nlv*100:.2f}%)")
        print(f"  Open Positions:   {len(pos)}")
        for sym, qty in pos.items():
            print(f"    {sym:<10} {qty:>8} shares")
    except Exception as e:
        print(f"  (error: {e})")
    print()


def _run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(30)


def run_live(args):
    mode_str = "PAPER" if PAPER_TRADE else "⚠  LIVE"
    log.info(f"Starting multi-strategy system  mode={mode_str}")

    if not PAPER_TRADE and not args.yes:
        confirm = input("⚠  Live trading mode — type YES to confirm: ").strip()
        if confirm != "YES":
            log.info("Aborted"); sys.exit(0)

    broker   = IBKRBroker()
    risk_mgr = RiskManager(broker)
    broker.connect()

    ipo_strat = HKIPOStrategy(broker, risk_mgr, HK_IPO)
    tz_strat  = TZArbStrategy(broker, risk_mgr, TZ_ARB)
    lt_port   = LongTermPortfolio(broker, risk_mgr, LONG_TERM_PORTFOLIO)
    tz_signals = {"data": []}

    # Schedule HK strategies (times in UTC)
    schedule.every().day.at("00:50").do(  # 08:50 HKT
        lambda: tz_signals.update({"data": tz_strat.compute()})
    )
    schedule.every().day.at("01:32").do(  # 09:32 HKT
        lambda: (ipo_strat.run(), tz_strat.execute(tz_signals["data"]))
    )
    schedule.every().day.at("07:55").do(  # 15:55 HKT
        lambda: (ipo_strat.close_all(), tz_strat.close_all())
    )
    schedule.every(5).minutes.do(lt_port.check_trailing_stops)
    schedule.every().day.at("15:00").do(   # 10am ET ≈ 15:00 UTC
        lambda: lt_port.rebalance() if now_et().day == 1 else None
    )

    threading.Thread(target=_run_scheduler, daemon=True).start()
    log.info("Scheduler started (HK IPO + TZ_ARB + LT rebalance + trailing stops)")

    engine = TradingEngine()
    try:
        engine.start()   # connects broker + enters main loop
    finally:
        log.info("Shutting down...")
        ipo_strat.close_all()
        tz_strat.close_all()
        engine._close_all_eod()
        broker.disconnect()
        log.info("Disconnected")


def run_status(args):
    broker = IBKRBroker()
    broker.connect()
    show_status(broker)

    lt = LongTermPortfolio(broker, None, LONG_TERM_PORTFOLIO)
    print("── Long-Term Portfolio ──────────────────────")
    try:
        print(lt.status().to_string(index=False))
    except Exception as e:
        print(f"  (error: {e})")
    print()

    from strategy.tz_arb import compute_signals
    sigs = compute_signals(threshold=TZ_ARB["adr_threshold"])
    print(f"── Timezone Arb Signals ({len(sigs)}) ────────────")
    for s in sigs:
        print(f"  {s['description']}  move={s['adr_move']:+.2%}")
    print()
    broker.disconnect()


def run_rebalance(args):
    broker = IBKRBroker()
    risk   = RiskManager(broker)
    broker.connect()
    lt     = LongTermPortfolio(broker, risk, LONG_TERM_PORTFOLIO)
    dry    = not args.yes
    log.info(f"Rebalancing  dry_run={dry}")
    trades = lt.rebalance(dry_run=dry)
    log.info(f"Done: {len(trades)} trade(s)")
    broker.disconnect()


def run_backtest(args):
    log.info("Running backtest...")
    from strategy.backtest import run as bt_run
    bt_run()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="IBKR Multi-Strategy System")
    p.add_argument("--backtest",  action="store_true")
    p.add_argument("--status",    action="store_true")
    p.add_argument("--rebalance", action="store_true")
    p.add_argument("--yes", "-y", action="store_true")
    args = p.parse_args()

    if   args.backtest:  run_backtest(args)
    elif args.status:    run_status(args)
    elif args.rebalance: run_rebalance(args)
    else:                run_live(args)
