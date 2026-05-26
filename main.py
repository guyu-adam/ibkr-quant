"""
quant — 多市场量化交易系统

统一入口，支持：
  python main.py                  # 启动实时/模拟交易
  python main.py --backtest       # 离线回测
  python main.py --status         # 账户状态 + 信号扫描
  python main.py --rebalance      # 长期组合再平衡
  python main.py --paper          # 启动模拟盘 Web 仪表盘
"""

import logging
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(__file__))

from config.settings import (
    IBKR_HOST, IBKR_PORT, IBKR_CLIENT, PAPER_TRADE, ACCOUNT_EQUITY,
    MAX_POSITION_PCT, MAX_TOTAL_EXPOSURE, MAX_DAILY_LOSS_PCT,
    STOP_LOSS_ATR_MULT, WATCHLIST, RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT,
    BAR_SIZE,
)
from core.risk import RiskManager
from core.data_feed import YFinanceFeed, CachedFeed
from strategies.fast_trading import MeanReversionStrategy, PositionSizer

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("logs/trading.log")],
)
log = logging.getLogger("main")


def run_backtest():
    """Run offline backtest."""
    log.info("Running backtest...")
    from strategies.fast_trading import MeanReversionStrategy
    from core.data_feed import YFinanceFeed

    feed = YFinanceFeed()
    strategy = MeanReversionStrategy({
        'rsi_oversold': RSI_OVERSOLD, 'rsi_overbought': RSI_OVERBOUGHT,
    })

    print("\n── Backtest ───────────────────────────────────")
    for sym in WATCHLIST:
        result = strategy.evaluate(feed, sym)
        print(f"  {sym:<8} RSI={result['rsi']:>5.1f}  score={result['score']:>4.0f}  "
              f"signal={result['signal']:<4}  {result.get('reason','')}")
    print()


def run_status():
    """Show account status and signal scan."""
    from interfaces.ibkr import IBKRBroker

    broker = IBKRBroker()
    broker.connect()

    print("\n── Account ────────────────────────────────────")
    try:
        nlv = broker.net_liquidation()
        pnl = broker.daily_pnl()
        pos = broker.positions()
        print(f"  Net Liquidation:  ${nlv:,.2f}")
        print(f"  Daily P&L:        ${pnl:,.2f}")
        print(f"  Open Positions:   {len(pos)}")
        for sym, qty in sorted(pos.items()):
            px = broker.last_price(sym)
            print(f"    {sym:<8} {qty:>6} shares  @ ${px:,.2f}  = ${qty*px:,.2f}")
    except Exception as e:
        print(f"  (error: {e})")
    print()

    feed = CachedFeed(YFinanceFeed(), ttl_seconds=300)
    strategy = MeanReversionStrategy({'rsi_oversold': RSI_OVERSOLD, 'rsi_overbought': RSI_OVERBOUGHT})

    print("── Signal Scan ────────────────────────────────")
    for sym in WATCHLIST:
        try:
            result = strategy.evaluate(feed, sym, broker.positions())
            print(f"  {sym:<8} RSI={result['rsi']:>5.1f}  score={result['score']:>4.0f}  "
                  f"signal={result['signal']:<4}  {result.get('reason','')}")
        except Exception as e:
            print(f"  {sym:<8} error: {e}")
    print()

    broker.disconnect()


def run_paper():
    """Start paper trading web dashboard."""
    from paper_trading.app import app
    log.info("Starting paper trading dashboard on http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="quant — Multi-Market Quant Trading System")
    p.add_argument("--backtest",  action="store_true", help="Offline backtest")
    p.add_argument("--status",    action="store_true", help="Account status + signal scan")
    p.add_argument("--rebalance", action="store_true", help="Force LT portfolio rebalance")
    p.add_argument("--paper",     action="store_true", help="Start paper trading dashboard")
    args = p.parse_args()

    if args.backtest:
        run_backtest()
    elif args.status:
        run_status()
    elif args.rebalance:
        from interfaces.ibkr import IBKRBroker
        from strategies.long_term import LongTermPortfolio
        from config.settings import LONG_TERM_PORTFOLIO
        broker = IBKRBroker()
        broker.connect()
        risk = RiskManager(broker)
        portfolio = LongTermPortfolio(broker, risk, LONG_TERM_PORTFOLIO)
        portfolio.rebalance(dry_run=False)
        broker.disconnect()
    elif args.paper:
        run_paper()
    else:
        p.print_help()
