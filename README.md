# ibkr-quant

Multi-strategy quantitative trading system for Interactive Brokers. Runs four strategies concurrently across US and Hong Kong markets.

## Strategies

### 1. US Momentum (intraday)
RSI mean-reversion + EMA trend filter on a configurable watchlist. Trades 5-min bars during regular market hours. ATR-based position sizing and stop-loss.

### 2. HK IPO First-Day Pop
Scans HKEX listings each morning. Fetches grey-market premium. If premium ≥ 15%, buys at HK market open with OCA bracket (target = 60% of grey premium, stop = 5% below IPO price). Closes EOD.

### 3. Timezone Arbitrage (ADR → HK)
If a US-listed ADR of a HK/China company moves ≥1.5% overnight, expects corresponding drift at HK open. Signals computed at 8:50 HKT, executed at 9:32 HKT.

Pairs: BABA/9988 · JD/9618 · PDD/9999 · BIDU/9888 · NIO/9866 · XPEV/9868 · LI/2015

### 4. Long-Term Portfolio
Passive basket (QQQ, SPY, NVDA, AAPL, MSFT, AMZN, TSLA, META) with monthly rebalancing, DCA on dips, 25% trailing stop.

## Setup

```bash
# 1. Open TWS or IB Gateway, enable API (port 7496 for paper, 7497 for live)
# 2. Install dependencies
pip install -r requirements.txt

# 3. Edit config/settings.py
#    IBKR_PORT = 7496  (paper)
#    PAPER_TRADE = True

# 4. Run
python main.py
```

## Commands

```bash
python main.py             # start trading (paper by default)
python main.py --status    # show positions + TZ_ARB signals
python main.py --rebalance # rebalance long-term portfolio
python main.py --backtest  # offline backtest (momentum)
```

## Architecture

```
main.py              ← entry point + scheduler
core/broker.py       ← ib_insync wrapper
core/engine.py       ← US momentum loop
core/risk.py         ← position sizing, daily halt
strategy/signals.py  ← RSI + EMA indicators
strategy/hk_ipo.py   ← HK IPO strategy
strategy/tz_arb.py   ← ADR→HK arbitrage
strategy/long_term.py ← passive portfolio
config/settings.py   ← all parameters
```

## Risk Notes

- Always run paper first (`PAPER_TRADE = True`) for at least 2 weeks.
- System halts US trading at `MAX_DAILY_LOSS_PCT` (default 2%).
- ADR timezone arbitrage historical win rate ~55-60%; use small sizes.
- HK grey market data scraped from third-party sites — may break if site changes.

## License

MIT — use at your own risk.
