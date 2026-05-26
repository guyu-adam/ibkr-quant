"""
quant — 多市场量化交易系统配置 v3

API keys are loaded from .env via python-dotenv.
Copy .env.example to .env and fill in your credentials.
"""

import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

# ═══════════════════════════════════════════════════════════════════════════════
# IBKR
# ═══════════════════════════════════════════════════════════════════════════════
IBKR_HOST   = os.getenv("IBKR_HOST", "127.0.0.1")
IBKR_PORT   = int(os.getenv("IBKR_PORT", "7497"))
IBKR_CLIENT = int(os.getenv("IBKR_CLIENT", "1"))
PAPER_TRADE = os.getenv("PAPER_TRADE", "true").lower() in ("1", "true", "yes")

# ═══════════════════════════════════════════════════════════════════════════════
# OKX
# ═══════════════════════════════════════════════════════════════════════════════
OKX_FLAG   = os.getenv("OKX_FLAG", "1")
OKX_DOMAIN = os.getenv("OKX_DOMAIN", "https://www.okx.com")
OKX_API_KEY = os.getenv("OKX_API_KEY", "")
OKX_SECRET  = os.getenv("OKX_SECRET", "")
OKX_PASSPHRASE = os.getenv("OKX_PASSPHRASE", "")

# ═══════════════════════════════════════════════════════════════════════════════
# Binance
# ═══════════════════════════════════════════════════════════════════════════════
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET  = os.getenv("BINANCE_SECRET", "")

# ═══════════════════════════════════════════════════════════════════════════════
# Charles Schwab
# ═══════════════════════════════════════════════════════════════════════════════
SCHWAB_API_KEY    = os.getenv("SCHWAB_API_KEY", "")
SCHWAB_SECRET     = os.getenv("SCHWAB_SECRET", "")
SCHWAB_CALLBACK   = os.getenv("SCHWAB_CALLBACK", "https://127.0.0.1:8080")

# ═══════════════════════════════════════════════════════════════════════════════
# 同花顺
# ═══════════════════════════════════════════════════════════════════════════════
THS_HOST    = os.getenv("THS_HOST", "127.0.0.1")
THS_PORT    = int(os.getenv("THS_PORT", "8010"))
THS_ACCOUNT = os.getenv("THS_ACCOUNT", "")

# ═══════════════════════════════════════════════════════════════════════════════
# 风控 (v3 — 分层熔断 + 分数凯利)
# ═══════════════════════════════════════════════════════════════════════════════
ACCOUNT_EQUITY      = 10_000
MAX_POSITION_PCT    = 0.10
MAX_TOTAL_EXPOSURE  = 0.80
MAX_DAILY_LOSS_PCT  = 0.02
MAX_WEEKLY_LOSS_PCT = 0.05
MAX_INTRADAY_LOSS_PCT = 0.015
STOP_LOSS_ATR_MULT  = 2.0
TRADE_RISK_PCT      = 0.01

# Kelly sizing
KELLY_FRACTION      = 0.5       # half-Kelly
KELLY_MAX_PCT       = 0.02     # cap at 2% per bet
KELLY_ROLLING_TRADES = 50      # rolling window for win/loss estimation
KELLY_MIN_TRADES     = 20      # min trades before Kelly kicks in

# Adaptive ATR stops
ATR_MULT_LOW_VOL   = 1.5       # VIX < 15
ATR_MULT_MID_VOL   = 2.0       # VIX 15-25
ATR_MULT_HIGH_VOL  = 3.0       # VIX > 25
VIX_LOW_THRESHOLD  = 15
VIX_HIGH_THRESHOLD = 25

# ═══════════════════════════════════════════════════════════════════════════════
# HMM 市场状态检测
# ═══════════════════════════════════════════════════════════════════════════════
HMM_N_STATES      = 3          # trend-up / sideways / trend-down
HMM_LOOKBACK      = 252        # 1 year training window
HMM_RETRAIN_FREQ  = 21         # retrain every 21 trading days
HMM_FEATURES      = ["ret_1d", "ret_5d", "ret_21d", "vol_5d", "vol_21d", "rsi_14"]

# ═══════════════════════════════════════════════════════════════════════════════
# Ensemble 策略融合
# ═══════════════════════════════════════════════════════════════════════════════
ENSEMBLE_METHOD     = "weighted"  # equal | weighted | voting
ENSEMBLE_LOOKBACK   = 60         # days for performance weighting
ENSEMBLE_MIN_SIGNAL = 0.3        # min blended signal to act

# ═══════════════════════════════════════════════════════════════════════════════
# Meta-Labeling
# ═══════════════════════════════════════════════════════════════════════════════
META_LABEL_ENABLED  = True
META_LABEL_CONFIDENCE = 0.6     # min probability to execute

# ═══════════════════════════════════════════════════════════════════════════════
# Walk-Forward 验证
# ═══════════════════════════════════════════════════════════════════════════════
WF_IS_YEARS    = 2
WF_OOS_MONTHS  = 6
WF_STEP_MONTHS = 3
WF_MIN_OOS_SHARPE = 0.3
WF_MAX_IS_OOS_RATIO = 2.0       # IS Sharpe / OOS Sharpe > 2 → overfit

# ═══════════════════════════════════════════════════════════════════════════════
# Alpha 因子库
# ═══════════════════════════════════════════════════════════════════════════════
ALPHA_FACTOR_SET = "full"       # basic | extended | full
ALPHA_TOP_K       = 20

# ═══════════════════════════════════════════════════════════════════════════════
# 美股 — 快速交易
# ═══════════════════════════════════════════════════════════════════════════════
US_WATCHLIST    = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN"]
WATCHLIST       = US_WATCHLIST   # backward-compat alias
RSI_PERIOD      = 14
RSI_OVERSOLD    = 30
RSI_OVERBOUGHT  = 70
MOM_FAST        = 10
MOM_SLOW        = 30
ATR_PERIOD      = 14
SIGNAL_COOLDOWN = 60

# ═══════════════════════════════════════════════════════════════════════════════
# 合约 — 网格
# ═══════════════════════════════════════════════════════════════════════════════
GRID_LEVELS       = 10
GRID_SPACING_ATR  = 2.0      # grid spacing = ATR * this
GRID_TREND_FILTER = True     # enable EMA trend filter
GRID_EMA_PERIOD   = 50       # EMA for trend direction

# ═══════════════════════════════════════════════════════════════════════════════
# 期权 — VIX 择时
# ═══════════════════════════════════════════════════════════════════════════════
OPTION_VIX_SELL  = 15        # VIX < this → sell premium
OPTION_VIX_HEDGE = 25        # VIX > this → buy protection
OPTION_VIX_HALT  = 35        # VIX > this → stop all option selling

# ═══════════════════════════════════════════════════════════════════════════════
# 杠杆 — 协整配对
# ═══════════════════════════════════════════════════════════════════════════════
PAIRS_Z_ENTRY     = 2.0
PAIRS_Z_EXIT      = 0.5
PAIRS_HALFLIFE_MIN = 5
PAIRS_HALFLIFE_MAX = 60
PAIRS_CORR_MIN    = 0.7

# ═══════════════════════════════════════════════════════════════════════════════
# 港股 — 慢速交易
# ═══════════════════════════════════════════════════════════════════════════════
TZ_ARB = {
    "adr_threshold": 0.015, "position_risk_pct": 0.01,
    "stop_pct": 0.02, "target_ratio": 2.0,
    "max_positions": 3, "allow_short": False, "hkd_usd_rate": 7.8,
}
HK_IPO = {
    "min_grey_premium": 0.15, "stop_pct": 0.05,
    "target_pct_of_premium": 0.60, "max_risk_per_trade": 0.015,
    "max_concurrent_positions": 2,
}

# ═══════════════════════════════════════════════════════════════════════════════
# 长期组合
# ═══════════════════════════════════════════════════════════════════════════════
LONG_TERM_PORTFOLIO = {
    "positions": {
        "QQQ": 0.25, "SPY": 0.20, "NVDA": 0.15,
        "AAPL": 0.10, "MSFT": 0.10, "AMZN": 0.10,
        "TSLA": 0.05, "META": 0.05,
    },
    "drift_threshold": 0.05, "dca_dip_pct": 0.15,
    "trailing_stop_pct": 0.25, "max_equity_pct": 0.60,
    # HRP
    "use_hrp": True,
    "hrp_method": "ward",        # ward | single | complete | average
    "cov_shrinkage": "ledoit_wolf",  # ledoit_wolf | oas | sample
    # Bootstrap
    "bootstrap_samples": 1000,
    "bootstrap_confidence": 0.05,  # 5th percentile worst-case
}

# ═══════════════════════════════════════════════════════════════════════════════
# Transformer (P2)
# ═══════════════════════════════════════════════════════════════════════════════
TRANSFORMER_ENABLED  = False
TRANSFORMER_D_MODEL  = 128
TRANSFORMER_N_HEADS  = 4
TRANSFORMER_N_LAYERS = 3
TRANSFORMER_SEQ_LEN  = 60
TRANSFORMER_HORIZON  = 5

# ═══════════════════════════════════════════════════════════════════════════════
# 运行时
# ═══════════════════════════════════════════════════════════════════════════════
MARKET_OPEN  = "09:30"
MARKET_CLOSE = "15:45"
BAR_SIZE     = "5 mins"
HK_MARKET_OPEN  = "09:30"
HK_MARKET_CLOSE = "16:00"
HK_PRE_OPEN     = "08:50"
