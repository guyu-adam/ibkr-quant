"""
IBKR 多策略量化交易系统
────────────────────────────────────────
即插即用 — 编辑 config/settings.py 后直接运行

用法:
  python main.py                 # 启动实时/模拟交易（基于 config 中的模式）
  python main.py --status        # 查看账户状态
  python main.py --backtest      # 离线回测
  python main.py --rebalance     # 强制长期组合再平衡

前置条件:
  1. IBKR TWS 或 Gateway 已启动
  2. TWS → API → 启用 Socket (端口 7497/7496)
  3. pip install ib_insync yfinance schedule beautifulsoup4 lxml
  4. PAPER_TRADE=True 先跑模拟盘确认策略无误
"""

import logging, sys, os, argparse
sys.path.insert(0, os.path.dirname(__file__))

from core.broker import IBKRBroker
from core.risk import RiskManager
from core.data_feed import YFinanceFeed, CachedFeed
from strategy.legacy.mean_reversion import MeanReversionStrategy, PositionSizer
from config.settings import (
    IBKR_HOST, IBKR_PORT, IBKR_CLIENT, PAPER_TRADE,
    ACCOUNT_EQUITY, MAX_POSITION_PCT, MAX_TOTAL_EXPOSURE,
    MAX_DAILY_LOSS_PCT, STOP_LOSS_ATR_MULT,
    WATCHLIST, RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT,
    TZ_ARB, HK_IPO, LONG_TERM_PORTFOLIO,
)

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("logs/trading.log")],
)
log = logging.getLogger("main")


def show_account(broker: IBKRBroker):
    """打印账户概览"""
    print("\n── Account ──────────────────────────────────")
    try:
        nlv = broker.net_liquidation()
        pnl = broker.daily_pnl()
        pos = broker.positions()
        if nlv is None or nlv <= 0:
            print(f"  Net Liquidation:  (unavailable)")
            print(f"  Daily P&L:        ${pnl:,.2f}")
        else:
            print(f"  Net Liquidation:  ${nlv:,.2f}")
            print(f"  Daily P&L:        ${pnl:,.2f}  ({pnl/nlv*100:.2f}%)")
        print(f"  Open Positions:   {len(pos)}")
        for sym, qty in sorted(pos.items()):
            px = broker.last_price(sym)
            mv = qty * px
            print(f"    {sym:<8} {qty:>6} shares  @ ${px:,.2f}  = ${mv:,.2f}")
    except Exception as e:
        print(f"  (error: {e})")
    print()


def run_live():
    """启动 IBKR 实时/模拟交易"""
    mode = "PAPER" if PAPER_TRADE else "LIVE"
    log.info(f"Starting IBKR trading  mode={mode}  host={IBKR_HOST}:{IBKR_PORT}")

    # ── 连接 ──────────────────────────────────────────────────────────────────
    broker = IBKRBroker()
    broker.connect()
    risk = RiskManager(broker)
    log.info(f"Connected  account={broker.account()}  equity≈${broker.net_liquidation() or ACCOUNT_EQUITY:,.0f}")

    # ── 策略初始化 ───────────────────────────────────────────────────────────
    feed = CachedFeed(YFinanceFeed(), ttl_seconds=300)
    strategy = MeanReversionStrategy({
        'rsi_period': RSI_PERIOD,
        'rsi_oversold': RSI_OVERSOLD,
        'rsi_overbought': RSI_OVERBOUGHT,
        'atr_period': 14,
        'atr_stop_mult': STOP_LOSS_ATR_MULT,
    })
    sizer = PositionSizer(base_pct=MAX_POSITION_PCT, max_pct=MAX_POSITION_PCT * 1.5)

    log.info(f"Strategy: {strategy.name} | Watchlist: {len(WATCHLIST)} symbols")
    log.info(f"Position sizing: base={sizer.base_pct:.0%} max={sizer.max_pct:.0%} slots={sizer.max_positions}")

    # ── 主循环（简化版 — 每 BAR_SIZE 分钟评估一次）────────────────────────────
    import time as _time
    from config.settings import BAR_SIZE

    bar_sec = 300  # 5 min
    if "min" in BAR_SIZE:
        bar_sec = int(BAR_SIZE.split()[0]) * 60

    log.info(f"Entering main loop  bar_interval={bar_sec}s  Ctrl+C to stop")
    try:
        while True:
            for symbol in WATCHLIST:
                try:
                    result = strategy.evaluate(feed, symbol, broker.positions())
                    sig = result['signal']

                    if sig == 'buy':
                        price = result['close']
                        atr_val = result['atr']
                        shares = sizer.size(
                            broker.net_liquidation() or ACCOUNT_EQUITY,
                            price, atr_val,
                        )
                        if shares > 0 and risk.approve(symbol, shares, price):
                            broker.market_order(symbol, shares, 'BUY')
                            log.info(f"BUY  {symbol} {shares}sh  score={result['score']}  {result['reason']}")

                    elif sig == 'sell':
                        qty = broker.positions().get(symbol, 0)
                        if qty > 0:
                            broker.market_order(symbol, qty, 'SELL')
                            log.info(f"SELL {symbol} {qty}sh  {result['reason']}")

                    elif result.get('new_stop'):
                        # 更新止损（仅日志，实际止损由 RiskManager 管理）
                        log.debug(f"{symbol} trailing_stop→{result['new_stop']:.2f}")

                except Exception as e:
                    log.error(f"{symbol}: {e}")

            _time.sleep(bar_sec)
    except KeyboardInterrupt:
        log.info("Shutting down...")
    finally:
        # 收盘清仓（日内策略需要）
        for sym, qty in broker.positions().items():
            if qty != 0:
                action = 'SELL' if qty > 0 else 'BUY'
                broker.market_order(sym, abs(qty), action)
                log.info(f"EOD close {sym} {qty}sh")
        broker.disconnect()
        log.info("Disconnected")


def run_status_cmd():
    """CLI: 查看账户和策略信号概览"""
    broker = IBKRBroker()
    broker.connect()
    show_account(broker)

    feed = CachedFeed(YFinanceFeed(), ttl_seconds=300)
    strategy = MeanReversionStrategy({
        'rsi_oversold': RSI_OVERSOLD,
        'rsi_overbought': RSI_OVERBOUGHT,
    })

    print("── Signal Scan ──────────────────────────────")
    for sym in WATCHLIST:
        try:
            result = strategy.evaluate(feed, sym, broker.positions())
            print(f"  {sym:<8} RSI={result['rsi']:>5.1f}  score={result['score']:>4.0f}  "
                  f"signal={result['signal']:<4}  {result.get('reason','')}")
        except Exception as e:
            print(f"  {sym:<8} error: {e}")
    print()
    broker.disconnect()


def run_backtest_cmd():
    """CLI: 离线回测"""
    log.info("Running backtest...")
    from strategy.legacy.backtest import run as bt_run
    bt_run()


def run_live_wrapper(args):
    """带安全确认的 live 交易入口"""
    if not PAPER_TRADE and not args.yes:
        confirm = input("⚠  LIVE trading — type YES to confirm: ").strip()
        if confirm != "YES":
            log.info("Aborted"); sys.exit(0)
    run_live()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="IBKR Multi-Strategy Quant System")
    p.add_argument("--backtest",  action="store_true", help="Offline backtest")
    p.add_argument("--status",    action="store_true", help="Account status + signal scan")
    p.add_argument("--rebalance", action="store_true", help="Force LT portfolio rebalance")
    p.add_argument("--yes", "-y", action="store_true", help="Skip live trading confirm")
    args = p.parse_args()

    if args.backtest:
        run_backtest_cmd()
    elif args.status:
        run_status_cmd()
    elif args.rebalance:
        # Minimal: connect + show status
        broker = IBKRBroker()
        broker.connect()
        show_account(broker)
        log.info("Rebalance: see strategy/long_term.py for full implementation")
        broker.disconnect()
    else:
        run_live_wrapper(args)
