"""
OKX Crypto Perpetual Swap Configuration
Setup:
  1. Rename .env.example to .env
  2. Fill in your OKX API Key / Secret / Passphrase
  3. Run: python -m crypto.main (DEMO) or python -m crypto.main --live
Without .env, the system runs in MockBroker mode (simulated trading).
"""

import os
from pathlib import Path

# ── .env loading ────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass

# ── OKX API credentials (None if not configured → MockBroker) ──────────────
OKX_API_KEY    = os.getenv("OKX_API_KEY")
OKX_SECRET_KEY = os.getenv("OKX_SECRET_KEY")
OKX_PASSPHRASE = os.getenv("OKX_PASSPHRASE")
OKX_DOMAIN     = "https://www.okx.com"

# ── Trade mode ──────────────────────────────────────────────────────────────
DEMO = True           # Set False for live trading
FLAG = "1" if DEMO else "0"

# ── Trading universe (USDT-margined perpetual swaps) ───────────────────────
SYMBOLS = [
    "BTC-USDT-SWAP",
    "ETH-USDT-SWAP",
    "SOL-USDT-SWAP",
]

# Hardcoded contract specs (fallback if API unavailable)
CT_VAL = {
    "BTC-USDT-SWAP": 0.01,
    "ETH-USDT-SWAP": 0.01,
    "SOL-USDT-SWAP": 0.1,
}
LOT_SZ = {
    "BTC-USDT-SWAP": 1,
    "ETH-USDT-SWAP": 1,
    "SOL-USDT-SWAP": 1,
}
MIN_SZ = {
    "BTC-USDT-SWAP": 1,
    "ETH-USDT-SWAP": 1,
    "SOL-USDT-SWAP": 1,
}

# ── Risk limits ─────────────────────────────────────────────────────────────
ACCOUNT_EQUITY       = 1000     # fallback USDT if API unavailable
MAX_POSITION_PCT     = 0.15     # max 15% equity per position
MAX_TOTAL_EXPOSURE   = 0.80     # max 80% equity deployed
MAX_DAILY_LOSS_PCT   = 0.03     # halt after 3% daily loss
TRADE_RISK_PCT       = 0.01     # risk 1% equity per trade
MAX_OPEN_POSITIONS   = 5        # max concurrent grid entries total
MAX_LEVERAGE         = 3.0      # soft cap on effective leverage

# ── Strategy parameters ─────────────────────────────────────────────────────
BB_PERIOD         = 20         # Bollinger Bands lookback
BB_STD            = 2.0        # standard deviations
RSI_PERIOD        = 14
RSI_OVERSOLD      = 30
RSI_OVERBOUGHT    = 70
ATR_PERIOD        = 14
VOL_LOOKBACK      = 20         # volume average lookback
VOL_SPIKE_RATIO   = 1.5        # vol > 1.5x avg = spike
GRID_LEVELS       = 3          # max grid entry layers
GRID_SPACING_PCT  = 0.01       # 1% between grid levels
TAKE_PROFIT_PCT   = 0.02       # 2% take-profit per entry
STOP_LOSS_PCT     = 0.015      # 1.5% stop-loss per entry
MIN_SCORE         = 40         # minimum signal score to enter
SIGNAL_COOLDOWN   = 60         # seconds between signals per symbol

# ── Runtime ─────────────────────────────────────────────────────────────────
BAR_INTERVAL    = "5m"         # candlestick interval
LOOP_SLEEP      = 10           # seconds between main loop ticks
CANDLE_LIMIT    = 100          # number of candles to fetch

# ── Logging ─────────────────────────────────────────────────────────────────
LOG_LEVEL   = "INFO"
LOG_DIR     = "logs"
