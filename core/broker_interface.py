"""
统一 Broker 接口 — 所有券商适配器必须实现的 ABC。

Unifies positions() → dict[str, float] and net_liquidation() → float
across IBKR, OKX, Binance, Schwab, THS, and SimulationBroker.
"""

from abc import ABC, abstractmethod


class BrokerInterface(ABC):
    """Every broker adapter (real or simulated) must implement this."""

    @abstractmethod
    def connect(self) -> None:
        """Establish connection to broker/exchange."""
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """Tear down connection."""
        ...

    @abstractmethod
    def net_liquidation(self) -> float:
        """Total account equity in base currency."""
        ...

    @abstractmethod
    def daily_pnl(self) -> float:
        """Realized P&L for the current trading day."""
        ...

    @abstractmethod
    def positions(self) -> dict[str, float]:
        """
        Current positions.

        Returns:
            {symbol: quantity} — positive = long, negative = short.
        """
        ...

    @abstractmethod
    def last_price(self, symbol: str) -> float:
        """Most recent trade price for a symbol."""
        ...

    @abstractmethod
    def market_order(self, symbol: str, shares: int, action: str) -> None:
        """
        Submit a market order.

        Args:
            symbol: ticker or instrument ID
            shares: quantity (positive)
            action: 'BUY' or 'SELL'
        """
        ...
