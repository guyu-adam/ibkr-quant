"""
慢速交易 — 港股 IPO 打新 + 时区套利 (ADR → 港股)

Holding period: 1-5 days. Lower frequency, event-driven.

Usage:
    from strategies.slow_trading import HkIpoStrategy, TimezoneArbitrageStrategy
"""

import logging
from core.strategy_base import BaseStrategy

log = logging.getLogger(__name__)


class HkIpoStrategy(BaseStrategy):
    """
    HK IPO Pop — 灰市溢价 ≥ 15% 时首日开盘买入，目标捕捉溢价 60%。

    Config keys:
        min_grey_premium (0.15):    min grey market premium to trigger
        stop_pct (0.05):            stop 5% below IPO price
        target_pct_of_premium (0.60): target 60% of grey premium
        max_risk_per_trade (0.015):  max 1.5% of equity at risk
        max_concurrent_positions (2): max simultaneous IPO positions
    """

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.min_grey_premium  = cfg.get("min_grey_premium", 0.15)
        self.stop_pct          = cfg.get("stop_pct", 0.05)
        self.target_ratio      = cfg.get("target_pct_of_premium", 0.60)
        self.max_risk_pct      = cfg.get("max_risk_per_trade", 0.015)
        self.max_positions     = cfg.get("max_concurrent_positions", 2)

    @property
    def name(self) -> str:
        return "hk_ipo"

    def on_bar(self, data: dict) -> list:
        # Event-driven — triggers on IPO listing days only
        return []

    def on_close(self) -> None:
        pass


class TimezoneArbitrageStrategy(BaseStrategy):
    """
    ADR → HK 时区套利

    US ADR overnight move ≥ 1.5% triggers HK open trade on the underlying.
    Exploits price discovery lag between US ADR and HK ordinary shares.

    Config keys:
        adr_threshold (0.015):    min ADR overnight move
        position_risk_pct (0.01): risk 1% equity per trade
        stop_pct (0.02):          2% hard stop
        target_ratio (2.0):       1:2 risk/reward
        max_positions (3):        max concurrent positions
    """

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.adr_threshold    = cfg.get("adr_threshold", 0.015)
        self.position_risk_pct = cfg.get("position_risk_pct", 0.01)
        self.stop_pct         = cfg.get("stop_pct", 0.02)
        self.target_ratio     = cfg.get("target_ratio", 2.0)
        self.max_positions    = cfg.get("max_positions", 3)
        self.allow_short      = cfg.get("allow_short", False)

    @property
    def name(self) -> str:
        return "timezone_arb"

    def on_bar(self, data: dict) -> list:
        return []

    def on_close(self) -> None:
        pass
