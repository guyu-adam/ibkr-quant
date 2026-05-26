"""
期权策略 v2 — VIX 状态择时 + Covered Call / Protective Put / Iron Condor。

Enhancements (P1):
  - VIX-based regime: sell premium when VIX<15, hedge when VIX>25, halt when VIX>35
  - Each strategy checks VIX before generating signals
"""

import logging
from core.strategy_base import BaseStrategy
from config.settings import OPTION_VIX_SELL, OPTION_VIX_HEDGE, OPTION_VIX_HALT

log = logging.getLogger(__name__)


def get_vix_regime(vix: float) -> str:
    """sell | hedge | halt | neutral"""
    if vix > OPTION_VIX_HALT:   return "halt"
    if vix > OPTION_VIX_HEDGE:  return "hedge"
    if vix < OPTION_VIX_SELL:   return "sell"
    return "neutral"


class CoveredCallStrategy(BaseStrategy):
    """Covered Call v2 — only sells calls in low-VIX regimes."""

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.delta        = cfg.get("delta", 0.30)
        self.dte           = cfg.get("dte", 30)
        self.roll_dte      = cfg.get("roll_dte", 7)
        self.min_premium   = cfg.get("min_premium", 0.01)
        self._vix = 20.0

    @property
    def name(self) -> str: return "covered_call"

    def set_vix(self, vix: float): self._vix = vix

    def on_bar(self, data: dict) -> list:
        regime = get_vix_regime(self._vix)
        if regime in ("halt", "hedge"):
            return []
        # TODO: options chain analysis via IBKR
        return []

    def on_close(self) -> None: pass


class ProtectivePutStrategy(BaseStrategy):
    """Protective Put v2 — increases hedge ratio in high-VIX."""

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.put_delta   = cfg.get("put_delta", -0.20)
        self.dte          = cfg.get("dte", 60)
        self.cost_pct     = cfg.get("cost_pct", 0.02)
        self._vix = 20.0

    @property
    def name(self) -> str: return "protective_put"

    def set_vix(self, vix: float): self._vix = vix

    def on_bar(self, data: dict) -> list:
        regime = get_vix_regime(self._vix)
        if regime == "hedge":
            # Increase put buying in high VIX
            self.cost_pct = 0.04
        else:
            self.cost_pct = 0.02
        return []

    def on_close(self) -> None: pass


class IronCondorStrategy(BaseStrategy):
    """Iron Condor v2 — only sells when VIX < sell threshold."""

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.short_delta = cfg.get("short_delta", 0.16)
        self.long_delta  = cfg.get("long_delta", 0.05)
        self.dte          = cfg.get("dte", 45)
        self.profit_pct   = cfg.get("profit_pct", 0.50)
        self.stop_pct     = cfg.get("stop_pct", 2.0)
        self._vix = 20.0

    @property
    def name(self) -> str: return "iron_condor"

    def set_vix(self, vix: float): self._vix = vix

    def on_bar(self, data: dict) -> list:
        regime = get_vix_regime(self._vix)
        if regime in ("halt", "hedge"):
            return []  # don't sell vol in high-VIX
        return []

    def on_close(self) -> None: pass
