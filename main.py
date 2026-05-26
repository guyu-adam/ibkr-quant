"""
quant — 多市场量化交易系统 v3

Usage:
  python main.py --backtest       离线回测
  python main.py --status         IBKR 账户状态
  python main.py --rebalance      长期组合再平衡
  python main.py --paper          模拟盘仪表盘
  python main.py --scan           全策略信号扫描
  python main.py --walkforward    参数 Walk-Forward 验证
  python main.py --alpha-scan     因子 IC/IR 分析
  python main.py --regime         市场状态检测
"""

import logging
import os
import argparse

from config.settings import (
    IBKR_HOST, IBKR_PORT, IBKR_CLIENT, PAPER_TRADE, ACCOUNT_EQUITY,
    WATCHLIST, RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT,
    ALPHA_FACTOR_SET, ALPHA_TOP_K,
)

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("logs/trading.log")],
)
log = logging.getLogger("main")


# ═══════════════════════════════════════════════════════════════════════════════
def run_backtest():
    """离线回测 — 所有策略信号扫描."""
    from core.data_feed import YFinanceFeed
    from strategies.fast_trading import MeanReversionStrategy
    from core.regime_detector import RegimeDetector

    feed = YFinanceFeed()
    strategy = MeanReversionStrategy({'rsi_oversold': RSI_OVERSOLD, 'rsi_overbought': RSI_OVERBOUGHT})
    regime = RegimeDetector()

    print("\n── Fast Trading Signal Scan ─────────────────")
    for sym in WATCHLIST:
        df = feed.fetch_history(sym)
        if df is not None:
            state = regime.fit_predict(df)
            result = strategy.evaluate(feed, sym)
            print(f"  {sym:<8} RSI={result['rsi']:>5.1f} score={result['score']:>4.0f} "
                  f"signal={result['signal']:<4} regime={state} {result.get('reason','')}")
    print()


def run_status():
    """IBKR 账户状态."""
    from interfaces.ibkr import IBKRBroker
    broker = IBKRBroker()
    broker.connect()
    print(f"\n── Account ──\n  NLV: ${broker.net_liquidation():,.2f}\n  P&L: ${broker.daily_pnl():,.2f}")
    pos = broker.positions()
    print(f"  Positions: {len(pos)}")
    for sym, qty in sorted(pos.items()):
        print(f"    {sym:<8} {qty:>6} shares @ ${broker.last_price(sym):,.2f}")
    broker.disconnect()
    print()


def run_rebalance():
    """长期组合再平衡 (HRP)."""
    from interfaces.ibkr import IBKRBroker
    from core.risk import RiskManager
    from strategies.long_term import LongTermPortfolio
    broker = IBKRBroker()
    broker.connect()
    risk = RiskManager(broker)
    portfolio = LongTermPortfolio(broker, risk)
    trades = portfolio.rebalance(dry_run=PAPER_TRADE)
    print(f"\n── Rebalance ──\n  Trades: {len(trades)}")
    for t in trades:
        print(f"    {t['action']} {t['shares']} {t['ticker']} drift={t['drift']:.2%}")
    broker.disconnect()
    print()


def run_paper():
    """模拟盘 Flask 仪表盘."""
    from paper_trading.app import app
    log.info("Paper trading dashboard: http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)


def run_alpha_scan():
    """Alpha 因子 IC/IR 分析."""
    from core.data_feed import YFinanceFeed
    from core.alpha_factors import compute_factors, compute_forward_returns
    from core.llm_alpha import LLMAlphaMiner

    feed = YFinanceFeed()
    print("\n── Alpha Factor IC Analysis ─────────────────")

    for sym in WATCHLIST[:3]:
        df = feed.fetch_history(sym)
        if df is None or len(df) < 100:
            continue
        factors = compute_factors(df)
        fwd = compute_forward_returns(df["close"], horizon=5)
        ic_cols = [c for c in factors.columns if c.endswith("_z")]

        ic_scores = {}
        common = factors.index.intersection(fwd.dropna().index)
        for col in ic_cols[:10]:
            corr = factors[col].loc[common].corr(fwd.loc[common], method="spearman")
            ic_scores[col] = corr

        top = sorted(ic_scores.items(), key=lambda x: abs(x[1]), reverse=True)[:5]
        print(f"\n  {sym} top factors:")
        for name, ic in top:
            print(f"    {name:<25} IC={ic:.4f}")

    print()


def run_regime():
    """市场状态检测."""
    from core.data_feed import YFinanceFeed
    from core.regime_detector import RegimeDetector

    feed = YFinanceFeed()
    rd = RegimeDetector()

    print("\n── Market Regime Detection ───────────────────")
    for sym in ["SPY", "QQQ"]:
        df = feed.fetch_history(sym)
        if df is not None:
            state = rd.fit_predict(df)
            labels = {0: "TREND-UP", 1: "SIDEWAYS", 2: "TREND-DOWN"}
            print(f"  {sym}: {labels.get(state, 'UNKNOWN')} (state={state})")
    print()


def run_walkforward():
    """Walk-Forward 参数验证."""
    from core.data_feed import YFinanceFeed
    from strategies.fast_trading import MeanReversionStrategy
    from core.walkforward import WalkForwardValidator

    feed = YFinanceFeed()
    df = feed.fetch_history("SPY")
    if df is None:
        print("No data")
        return

    param_grid = {
        "rsi_period": [7, 14, 21],
        "rsi_oversold": [25, 30, 35],
        "atr_stop_mult": [1.5, 2.0, 2.5],
    }

    wfv = WalkForwardValidator(MeanReversionStrategy, param_grid, df)
    results = wfv.run()
    if not results.empty:
        print("\n── Walk-Forward Results ──────────────────────")
        print(results[["is_sharpe", "oos_sharpe", "is_oos_ratio", "overfit"]].to_string())
        avg_oos = results["oos_sharpe"].mean()
        print(f"\n  Avg OOS Sharpe: {avg_oos:.3f}")
    print()


# ═══════════════════════════════════════════════════════════════════════════════
def main():
    """CLI entry point — invoked via `quant` command after pip install."""
    p = argparse.ArgumentParser(description="quant v3 — Multi-Market Quant System")
    p.add_argument("--backtest",    action="store_true", help="Signal scan")
    p.add_argument("--status",      action="store_true", help="Account status")
    p.add_argument("--rebalance",   action="store_true", help="Portfolio rebalance")
    p.add_argument("--paper",       action="store_true", help="Paper trading dashboard")
    p.add_argument("--scan",        action="store_true", help="Full strategy scan")
    p.add_argument("--alpha-scan",  action="store_true", help="Alpha factor IC analysis")
    p.add_argument("--regime",      action="store_true", help="Market regime detection")
    p.add_argument("--walkforward", action="store_true", help="Walk-forward validation")
    args = p.parse_args()

    if args.backtest:
        run_backtest()
    elif args.status:
        run_status()
    elif args.rebalance:
        run_rebalance()
    elif args.paper:
        run_paper()
    elif args.alpha_scan:
        run_alpha_scan()
    elif args.regime:
        run_regime()
    elif args.walkforward:
        run_walkforward()
    elif args.scan:
        run_backtest()
    else:
        p.print_help()


if __name__ == "__main__":
    main()
