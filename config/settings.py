"""
IBKR Multi-Strategy Configuration
───────────────────────────────────
Setup:
  1. Open TWS or IB Gateway
  2. TWS → Edit → Global Configuration → API → Settings
     ✓ Enable ActiveX and Socket Clients
     Port: 7497 (TWS live) | 7496 (TWS paper) | 4001 (Gateway live) | 4002 (Gateway paper)
  3. Set PAPER_TRADE = True until you have validated the strategies
"""

# ── IBKR connection ───────────────────────────────────────────────────────────
IBKR_HOST   = "127.0.0.1"
IBKR_PORT   = 7497        # 7497=TWS live | 7496=TWS paper | 4001=GW live | 4002=GW paper
IBKR_CLIENT = 1
PAPER_TRADE = True        # ← flip to False only after paper testing

# ── account risk limits ───────────────────────────────────────────────────────
ACCOUNT_EQUITY     = 10_000   # USD — used as fallback if IB can't return NLV
MAX_POSITION_PCT   = 0.10     # max 10% of equity in any single position
MAX_TOTAL_EXPOSURE = 0.80     # max 80% of equity deployed
MAX_DAILY_LOSS_PCT = 0.02     # halt trading after 2% daily drawdown
STOP_LOSS_ATR_MULT = 2.0      # stop = entry ± 2×ATR(14)

# ── Momentum strategy (US stocks, intraday) ───────────────────────────────────
WATCHLIST       = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN"]
RSI_PERIOD      = 14
RSI_OVERSOLD    = 30
RSI_OVERBOUGHT  = 70
MOM_FAST        = 10
MOM_SLOW        = 30
ATR_PERIOD      = 14
SIGNAL_COOLDOWN = 60      # seconds between signals for same ticker

# ── Timezone Arbitrage strategy (HK stocks at HK open) ───────────────────────
TZ_ARB = {
    "adr_threshold":     0.015,   # min 1.5% overnight ADR move to trigger
    "position_risk_pct": 0.01,    # risk 1% of equity per TZ trade
    "stop_pct":          0.02,    # 2% stop
    "target_ratio":      2.0,     # 1:2 risk/reward
    "max_positions":     3,
    "allow_short":       False,
    "hkd_usd_rate":      7.8,
}

# ── HK IPO strategy ───────────────────────────────────────────────────────────
HK_IPO = {
    "min_grey_premium":          0.15,   # skip if grey market < 15% premium
    "stop_pct":                  0.05,   # stop 5% below IPO price
    "target_pct_of_premium":     0.60,   # target = 60% of grey market premium
    "max_risk_per_trade":        0.015,  # 1.5% of equity at risk per IPO
    "max_concurrent_positions":  2,
}

# ── Long-term portfolio ───────────────────────────────────────────────────────
LONG_TERM_PORTFOLIO = {
    "positions": {
        "QQQ":  0.25,   # Nasdaq 100
        "SPY":  0.20,   # S&P 500
        "NVDA": 0.15,   # AI / Semis
        "AAPL": 0.10,
        "MSFT": 0.10,
        "AMZN": 0.10,
        "TSLA": 0.05,
        "META": 0.05,
    },
    "drift_threshold":   0.05,   # rebalance when drift > 5%
    "dca_dip_pct":       0.15,   # DCA if price > 15% below 52w high
    "trailing_stop_pct": 0.25,   # exit long-term position at 25% drawdown
    "max_equity_pct":    0.60,   # max 60% of account in long-term bucket
}

# ── Runtime (US Eastern time) ─────────────────────────────────────────────────
MARKET_OPEN  = "09:30"
MARKET_CLOSE = "15:45"
BAR_SIZE     = "5 mins"

# ── Hong Kong time ────────────────────────────────────────────────────────────
HK_MARKET_OPEN  = "09:30"   # HKT
HK_MARKET_CLOSE = "16:00"   # HKT
HK_PRE_OPEN     = "08:50"   # compute TZ_ARB signals before open
