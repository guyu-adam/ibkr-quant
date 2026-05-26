"""
模拟盘核心引擎 — A 股纸上交易
"""

import logging

from core.broker_interface import BrokerInterface
from core.data_feed import TencentFeed, DataFeed
from core.risk import RiskManager

log = logging.getLogger(__name__)


class SimulationBroker(BrokerInterface):
    """Simulated broker for paper trading — tracks virtual portfolio."""

    def __init__(self, initial_equity=100_000):
        self._equity = initial_equity
        self._positions: dict[str, dict] = {}
        self._pnl = 0.0
        self._feed = TencentFeed()
        self._connected = False

    def connect(self):
        self._connected = True

    def disconnect(self):
        self._connected = False

    def net_liquidation(self) -> float:
        return self._equity

    def daily_pnl(self) -> float:
        return self._pnl

    def positions(self) -> dict[str, float]:
        """Unified interface: {symbol: quantity}."""
        return {
            sym: pos["shares"]
            for sym, pos in self._positions.items()
        }

    def positions_detail(self) -> dict:
        """Full position details: {symbol: {shares, avg_cost}}."""
        return self._positions

    def last_price(self, symbol: str) -> float:
        return self._feed.fetch_realtime([symbol]).get(symbol, 0.0)

    def market_order(self, symbol: str, shares: int, action: str):
        price = self.last_price(symbol)
        if price <= 0:
            return
        action = action.upper()
        if action == "BUY":
            cost = shares * price * 1.0003  # stamp + commission
            if cost > self._equity * 0.3:
                return
            self._equity -= cost
            self._positions[symbol] = self._positions.get(symbol, {
                "shares": 0, "avg_cost": price,
            })
            pos = self._positions[symbol]
            old_cost = pos["avg_cost"]
            old_qty = pos["shares"]
            pos["shares"] = old_qty + shares
            if old_qty > 0:
                pos["avg_cost"] = (old_cost * old_qty + price * shares) / pos["shares"]
            else:
                pos["avg_cost"] = price
        elif action == "SELL" and symbol in self._positions:
            pos = self._positions[symbol]
            qty = min(abs(shares), pos["shares"])
            self._equity += qty * price * 0.9987
            self._pnl += qty * (price - pos["avg_cost"])
            pos["shares"] -= qty
            if pos["shares"] <= 0:
                del self._positions[symbol]
        log.info(f"[PAPER] {action} {shares} {symbol} @ {price:.2f}")


class PaperTradingEngine:
    """Main paper trading loop — runs strategies against simulated broker."""

    def __init__(self, strategy, broker=None, data_feed=None):
        self.strategy = strategy
        self.broker = broker or SimulationBroker()
        self.feed = data_feed or TencentFeed()
        self.risk = RiskManager(self.broker)

    def run_once(self, symbols: list[str]):
        for sym in symbols:
            try:
                price = self.broker.last_price(sym)
                if price <= 0:
                    continue
                data = {"symbol": sym, "close": price}
                signals = self.strategy.on_bar(data)
                for sig in signals:
                    if sig.get("signal") == "buy":
                        size = self.risk.position_size(price, price * 0.02)
                        if size > 0 and self.risk.approve(sym, size, price):
                            self.broker.market_order(sym, size, "BUY")
                    elif sig.get("signal") == "sell":
                        qty = self.broker.positions().get(sym, 0)
                        if qty > 0:
                            self.broker.market_order(sym, qty, "SELL")
            except Exception as e:
                log.error(f"[PAPER] {sym}: {e}")
