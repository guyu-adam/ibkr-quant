"""
quant_toolkit — Open-source quantitative analysis toolkit
integrated with the IBKR multi-strategy system.

Modules:
    indicators   — Technical indicators (RSI, MACD, EMA, ATR, BB, OBV)
    portfolio    — Portfolio optimization (max Sharpe, min vol, risk parity)
    analytics    — Performance analytics (full report, key metrics)
    ibkr_extended — Extended IBKR broker interface

NOTE: portfolio and analytics modules depend on optional packages
(PyPortfolioOpt, quantstats). Import failures are logged but non-fatal.
"""

import logging

_log = logging.getLogger(__name__)

# ── indicators (ta) — required ───────────────────────────────────────────────
from quant_toolkit.indicators import rsi, macd, ema, atr, bollinger_bands, obv

# ── portfolio (PyPortfolioOpt, scipy) — optional ─────────────────────────────
try:
    from quant_toolkit.portfolio import max_sharpe, min_volatility, risk_parity
except ImportError as e:
    _log.warning("quant_toolkit.portfolio unavailable: %s", e)
    max_sharpe = None       # type: ignore
    min_volatility = None   # type: ignore
    risk_parity = None      # type: ignore

# ── analytics (quantstats) — optional ─────────────────────────────────────────
try:
    from quant_toolkit.analytics import full_report, key_metrics
except ImportError as e:
    _log.warning("quant_toolkit.analytics unavailable: %s", e)
    full_report = None   # type: ignore
    key_metrics = None   # type: ignore

# ── ibkr_extended (ib_insync) — optional ─────────────────────────────────────
try:
    from quant_toolkit.ibkr_extended import IBKRBrokerExtended
except ImportError as e:
    _log.warning("quant_toolkit.ibkr_extended unavailable: %s", e)
    IBKRBrokerExtended = None   # type: ignore

__all__ = [
    # indicators
    "rsi", "macd", "ema", "atr", "bollinger_bands", "obv",
    # portfolio
    "max_sharpe", "min_volatility", "risk_parity",
    # analytics
    "full_report", "key_metrics",
    # ibkr
    "IBKRBrokerExtended",
]
