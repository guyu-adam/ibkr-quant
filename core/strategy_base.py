"""
统一策略抽象基类

所有策略（动量、港股IPO、时区套利、长期组合、月度轮动、纸上交易）
应实现此接口，确保 on_bar / on_close / name 签名一致。

使用方式：
    from core.strategy_base import BaseStrategy

    class MyStrategy(BaseStrategy):
        @property
        def name(self) -> str:
            return "my_strategy"

        def on_bar(self, data: dict) -> list:
            ...

        def on_close(self) -> None:
            ...
"""

from abc import ABC, abstractmethod


class BaseStrategy(ABC):
    """所有交易策略的抽象基类"""

    @abstractmethod
    def on_bar(self, data: dict) -> list:
        """
        每根 bar 调用一次（或每个评估周期）。
        返回 [Signal, ...] 列表，无信号返回空列表。
        """
        ...

    @abstractmethod
    def on_close(self) -> None:
        """收盘时调用（清仓、风控重置等）"""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """策略唯一标识名称"""
        ...

    def start(self) -> None:
        """可选：策略启动时的初始化（连接数据源等）"""
        pass

    def stop(self) -> None:
        """可选：策略停止后的清理（断开连接等）"""
        pass
