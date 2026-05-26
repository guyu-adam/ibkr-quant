"""
合约策略 — OKX 永续合约网格 + Binance 合约。
"""

import logging
import pandas as pd
import numpy as np

from core.strategy_base import BaseStrategy

log = logging.getLogger(__name__)


class GridScalpStrategy(BaseStrategy):
    """
    永续合约网格震荡策略

    Configured for OKX perpetual swaps. Uses grid of buy/sell orders
    at fixed intervals around a mid-price. Re-enters positions on pullbacks.
    """

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.grid_levels    = cfg.get("grid_levels", 10)
        self.grid_spacing   = cfg.get("grid_spacing", 0.005)   # 0.5%
        self.position_pct   = cfg.get("position_pct", 0.05)    # 5% per grid level
        self.stop_loss_pct  = cfg.get("stop_loss_pct", 0.03)
        self.take_profit_pct = cfg.get("take_profit_pct", 0.02)
        self._mid_price     = 0.0
        self._orders: dict[str, dict] = {}

    @property
    def name(self) -> str:
        return "grid_scalp"

    def on_bar(self, data: dict) -> list:
        price = data.get("close", 0)
        if price <= 0:
            return []

        if self._mid_price == 0:
            self._mid_price = price
            self._build_grid(price)

        signals = []

        # Check if price moved enough to trigger grid rebal
        drift = abs(price - self._mid_price) / self._mid_price
        if drift > self.grid_spacing * 2:
            self._mid_price = price
            self._build_grid(price)

        # Check grid level fills
        for level_price, order in list(self._orders.items()):
            if order["side"] == "BUY" and price <= level_price:
                signals.append({
                    "signal": "buy", "price": price,
                    "size": order["size"], "reason": f"grid_buy @ {level_price:.4f}",
                })
                del self._orders[level_price]
            elif order["side"] == "SELL" and price >= level_price:
                signals.append({
                    "signal": "sell", "price": price,
                    "size": order["size"], "reason": f"grid_sell @ {level_price:.4f}",
                })
                del self._orders[level_price]

        return signals

    def on_close(self) -> None:
        self._orders.clear()

    def _build_grid(self, mid: float):
        self._orders.clear()
        for i in range(1, self.grid_levels + 1):
            offset = self.grid_spacing * i
            self._orders[round(mid * (1 - offset), 4)] = {
                "side": "BUY", "size": self.position_pct,
            }
            self._orders[round(mid * (1 + offset), 4)] = {
                "side": "SELL", "size": self.position_pct,
            }
