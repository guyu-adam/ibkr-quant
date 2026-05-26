"""
期权策略 — 备兑看涨、保护性看跌、铁鹰组合
"""

import logging
from core.strategy_base import BaseStrategy

log = logging.getLogger(__name__)


class CoveredCallStrategy(BaseStrategy):
    """Covered Call: 持有正股 + 卖出虚值看涨期权."""

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.delta        = cfg.get("delta", 0.30)       # target short call delta
        self.dte           = cfg.get("dte", 30)            # days to expiry
        self.roll_dte      = cfg.get("roll_dte", 7)        # roll when DTE <= this
        self.min_premium   = cfg.get("min_premium", 0.01)  # min premium as % of underlying

    @property
    def name(self) -> str:
        return "covered_call"

    def on_bar(self, data: dict) -> list:
        # TODO: Implement options chain analysis via IBKR
        return []

    def on_close(self) -> None:
        pass


class ProtectivePutStrategy(BaseStrategy):
    """Protective Put: 持有正股 + 买入看跌期权."""

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.put_delta    = cfg.get("put_delta", -0.20)
        self.dte           = cfg.get("dte", 60)
        self.cost_pct      = cfg.get("cost_pct", 0.02)     # max 2% of position for put

    @property
    def name(self) -> str:
        return "protective_put"

    def on_bar(self, data: dict) -> list:
        return []

    def on_close(self) -> None:
        pass


class IronCondorStrategy(BaseStrategy):
    """Iron Condor: 卖出宽跨式 + 买入保护，赚时间价值."""

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.short_delta  = cfg.get("short_delta", 0.16)
        self.long_delta   = cfg.get("long_delta", 0.05)
        self.dte           = cfg.get("dte", 45)
        self.profit_pct    = cfg.get("profit_pct", 0.50)    # close at 50% max profit
        self.stop_pct      = cfg.get("stop_pct", 2.0)       # stop at 2x credit received

    @property
    def name(self) -> str:
        return "iron_condor"

    def on_bar(self, data: dict) -> list:
        return []

    def on_close(self) -> None:
        pass
