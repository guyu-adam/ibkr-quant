"""
合约策略 v2 — 动态网格间距(ATR-based) + EMA 趋势过滤 + 状态持久化。

Enhancements (P0):
  - ATR-based dynamic grid spacing (high vol → wider grid)
  - EMA(50) trend filter: only long grid above EMA, short grid below
  - JSON state persistence for crash recovery
"""

import json
import os
import logging
import numpy as np

from core.strategy_base import BaseStrategy
from core.indicators import ema
from config.settings import (
    GRID_LEVELS, GRID_SPACING_ATR, GRID_TREND_FILTER, GRID_EMA_PERIOD,
)

log = logging.getLogger(__name__)

def _state_file(instance_id: str = "default") -> str:
    return f"grid_{instance_id}.json"


class GridScalpStrategy(BaseStrategy):
    """永续合约网格震荡策略 v2 — 动态间距 + 趋势过滤."""

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.grid_levels     = cfg.get("grid_levels", GRID_LEVELS)
        self.spacing_atr     = cfg.get("grid_spacing_atr", GRID_SPACING_ATR)
        self.trend_filter    = cfg.get("trend_filter", GRID_TREND_FILTER)
        self.ema_period      = cfg.get("ema_period", GRID_EMA_PERIOD)
        self.position_pct    = cfg.get("position_pct", 0.05)
        self.instance_id     = cfg.get("instance_id", "default")
        self._mid_price      = 0.0
        self._orders: dict[float, dict] = {}  # price → {side, size}
        self._price_history: list[float] = []
        self._load_state()

    @property
    def name(self) -> str:
        return "grid_scalp"

    def on_bar(self, data: dict) -> list:
        price = data.get("close", 0)
        if price <= 0:
            return []

        self._price_history.append(price)
        if len(self._price_history) > 200:
            self._price_history = self._price_history[-200:]

        signals = []

        # Trend filter: determine allowed direction
        trend_allowed = "both"
        if self.trend_filter and len(self._price_history) >= self.ema_period:
            ema_val = ema(self._price_history, self.ema_period)
            if price > ema_val:
                trend_allowed = "long"   # only build long-side grid
            else:
                trend_allowed = "short"  # only build short-side grid

        # Initialize or re-center grid
        atr_val = self._calc_atr()
        dynamic_spacing = (atr_val / price) * self.spacing_atr if atr_val > 0 else 0.005

        if self._mid_price == 0 or abs(price - self._mid_price) / self._mid_price > dynamic_spacing * 3:
            self._mid_price = price
            self._build_grid(price, dynamic_spacing, trend_allowed)

        # Check grid fills
        for level_price in sorted(self._orders.keys()):
            order = self._orders[level_price]
            if order["side"] == "BUY" and price <= level_price:
                signals.append({"signal": "buy", "price": price, "size": order["size"],
                               "reason": f"grid_buy @ {level_price:.4f}"})
                del self._orders[level_price]
            elif order["side"] == "SELL" and price >= level_price:
                signals.append({"signal": "sell", "price": price, "size": order["size"],
                               "reason": f"grid_sell @ {level_price:.4f}"})
                del self._orders[level_price]

        self._save_state()
        return signals

    def on_close(self) -> None:
        self._orders.clear()
        sf = _state_file(self.instance_id)
        if os.path.exists(sf):
            os.remove(sf)

    def _build_grid(self, mid: float, spacing: float, trend: str):
        self._orders.clear()
        for i in range(1, self.grid_levels + 1):
            offset = spacing * i
            if trend in ("both", "long"):
                self._orders[round(mid * (1 - offset), 4)] = {
                    "side": "BUY", "size": self.position_pct}
            if trend in ("both", "short"):
                self._orders[round(mid * (1 + offset), 4)] = {
                    "side": "SELL", "size": self.position_pct}

    def _calc_atr(self) -> float:
        if len(self._price_history) < 15:
            return 0.0
        prices = np.array(self._price_history[-15:])
        diffs = np.abs(np.diff(prices))
        return float(np.mean(diffs))

    def _save_state(self):
        try:
            state = {"mid_price": self._mid_price, "orders": self._orders}
            with open(_state_file(self.instance_id), "w") as f:
                json.dump(state, f, default=str)
        except Exception:
            pass

    def _load_state(self):
        try:
            sf = _state_file(self.instance_id)
            if os.path.exists(sf):
                with open(sf) as f:
                    state = json.load(f)
                self._mid_price = state.get("mid_price", 0.0)
                self._orders = {float(k): v for k, v in state.get("orders", {}).items()}
                log.info(f"Loaded grid state: mid={self._mid_price}, {len(self._orders)} orders")
        except Exception:
            pass
