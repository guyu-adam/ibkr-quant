"""
策略抽象基类 — 所有策略（合约、期权、杠杆、快速、慢速、长期）的统一接口。
"""

from abc import ABC, abstractmethod


class BaseStrategy(ABC):
    """All trading strategies inherit from this."""

    @abstractmethod
    def on_bar(self, data: dict) -> list:
        """Called each bar/evaluation cycle. Returns [Signal, ...]."""
        ...

    @abstractmethod
    def on_close(self) -> None:
        """Called at market close (cleanup, EOD processing)."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique strategy identifier."""
        ...

    def start(self) -> None:
        """Optional: init connections, load state, etc."""
        pass

    def stop(self) -> None:
        """Optional: cleanup, disconnect, save state."""
        pass
