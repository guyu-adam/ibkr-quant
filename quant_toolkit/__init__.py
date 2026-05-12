"""
quant_toolkit — Open-source quantitative analysis toolkit
integrated with the IBKR multi-strategy system.

Modules:
    indicators   — Technical indicators (RSI, MACD, EMA, ATR, BB, OBV)
    portfolio    — Portfolio optimization (max Sharpe, min vol, risk parity)
    analytics    — Performance analytics (full report, key metrics)
    ibkr_extended — Extended IBKR broker interface
"""

from quant_toolkit.indicators import rsi, macd, ema, atr, bollinger_bands, obv
from quant_toolkit.portfolio import max_sharpe, min_volatility, risk_parity
from quant_toolkit.analytics import full_report, key_metrics
from quant_toolkit.ibkr_extended import IBKRBrokerExtended

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
