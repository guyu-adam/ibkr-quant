"""
Unit tests for core/strategy_base.py — abstract strategy interface.
"""
import unittest
from unittest.mock import MagicMock
from core.strategy_base import BaseStrategy


class TestBaseStrategyInterface(unittest.TestCase):
    """Verify BaseStrategy enforces the required interface."""

    def test_cannot_instantiate_abstract(self):
        """Instantiating BaseStrategy directly should raise TypeError."""
        with self.assertRaises(TypeError):
            BaseStrategy()  # type: ignore

    def test_concrete_subclass_instantiable(self):
        """A subclass implementing all abstract methods should be instantiable."""

        class MyStrategy(BaseStrategy):
            @property
            def name(self) -> str:
                return "test_strategy"

            def on_bar(self, data: dict) -> list:
                return []

            def on_close(self) -> None:
                pass

        s = MyStrategy()
        self.assertEqual(s.name, "test_strategy")
        self.assertEqual(s.on_bar({}), [])
        s.on_close()  # should not raise
        s.start()     # default no-op
        s.stop()      # default no-op


class TestPartialImplementationFails(unittest.TestCase):
    """Missing any abstract method should prevent instantiation."""

    def test_missing_on_bar(self):
        class NoOnBar(BaseStrategy):
            @property
            def name(self) -> str:
                return "broken"

            def on_close(self) -> None:
                pass

        with self.assertRaises(TypeError):
            NoOnBar()  # type: ignore

    def test_missing_on_close(self):
        class NoOnClose(BaseStrategy):
            @property
            def name(self) -> str:
                return "broken"

            def on_bar(self, data: dict) -> list:
                return []

        with self.assertRaises(TypeError):
            NoOnClose()  # type: ignore

    def test_missing_name(self):
        class NoName(BaseStrategy):
            def on_bar(self, data: dict) -> list:
                return []

            def on_close(self) -> None:
                pass

        with self.assertRaises(TypeError):
            NoName()  # type: ignore


class TestStrategyLifecycle(unittest.TestCase):
    """start/stop lifecycle hooks."""

    def test_default_start_stop_noop(self):
        class S(BaseStrategy):
            @property
            def name(self) -> str:
                return "lifecycle"

            def on_bar(self, data: dict) -> list:
                return []

            def on_close(self) -> None:
                pass

        s = S()
        # start/stop should not raise (default pass)
        s.start()
        s.stop()

    def test_custom_start_stop(self):
        tracker = {"started": False, "stopped": False}

        class S(BaseStrategy):
            @property
            def name(self) -> str:
                return "lifecycle"

            def on_bar(self, data: dict) -> list:
                return []

            def on_close(self) -> None:
                pass

            def start(self):
                tracker["started"] = True

            def stop(self):
                tracker["stopped"] = True

        s = S()
        s.start()
        s.stop()
        self.assertTrue(tracker["started"])
        self.assertTrue(tracker["stopped"])


if __name__ == "__main__":
    unittest.main()
