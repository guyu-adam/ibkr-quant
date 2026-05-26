"""
杠杆策略 — 杠杆 ETF 配对、保证金交易、永续合约杠杆
"""

import logging
from core.strategy_base import BaseStrategy

log = logging.getLogger(__name__)


class LeveragedETFStrategy(BaseStrategy):
    """
    杠杆 ETF 趋势追踪

    Examples: TQQQ (3x QQQ), SOXL (3x SOX), UPRO (3x SPY).
    Uses EMA trend filter + volatility-adjusted sizing.
    """

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.ema_fast      = cfg.get("ema_fast", 20)
        self.ema_slow      = cfg.get("ema_slow", 50)
        self.vol_stop_atr  = cfg.get("vol_stop_atr", 2.0)
        self.max_hold_days = cfg.get("max_hold_days", 20)
        self._days_held: dict[str, int] = {}

    @property
    def name(self) -> str:
        return "leveraged_etf"

    def on_bar(self, data: dict) -> list:
        return []

    def on_close(self) -> None:
        pass


class MarginLongShortStrategy(BaseStrategy):
    """
    保证金多空配对策略

    Pair trade: long strong + short weak within same sector.
    Market-neutral when perfectly hedged.
    """

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.lookback       = cfg.get("lookback", 60)
        self.entry_zscore   = cfg.get("entry_zscore", 2.0)
        self.exit_zscore    = cfg.get("exit_zscore", 0.5)
        self.pairs: list[tuple[str, str]] = cfg.get("pairs", [])

    @property
    def name(self) -> str:
        return "margin_long_short"

    def on_bar(self, data: dict) -> list:
        return []

    def on_close(self) -> None:
        pass
