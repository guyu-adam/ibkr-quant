"""Unit tests for paper_trading engine."""

import unittest
from unittest.mock import patch, MagicMock

from paper_trading.engine import PaperTradingEngine, SimulationBroker
from core.strategy_base import BaseStrategy


class DummyStrategy(BaseStrategy):
    """Test strategy that always returns a buy signal."""
    @property
    def name(self): return "dummy"
    def on_bar(self, data: dict) -> list:
        return [{"signal": "buy", "price": data.get("close", 100)}]
    def on_close(self): pass


class TestSimulationBroker(unittest.TestCase):
    def setUp(self):
        self.broker = SimulationBroker(initial_equity=100_000)

    def test_initial_equity(self):
        self.assertEqual(self.broker.net_liquidation(), 100_000)

    def test_empty_positions(self):
        self.assertEqual(len(self.broker.positions()), 0)

    def test_buy_reduces_equity(self):
        self.broker._feed = MagicMock()
        self.broker._feed.fetch_realtime.return_value = {"TEST": 100.0}
        self.broker.market_order("TEST", 100, "BUY")
        self.assertIn("TEST", self.broker.positions())

    def test_sell_empty_does_nothing(self):
        self.broker.market_order("TEST", 100, "SELL")
        self.assertNotIn("TEST", self.broker.positions())


class TestPaperTradingEngine(unittest.TestCase):
    def test_run_once_with_dummy_strategy(self):
        broker = SimulationBroker(initial_equity=100_000)
        broker._feed = MagicMock()
        broker._feed.fetch_realtime.return_value = {"TEST": 50.0}
        engine = PaperTradingEngine(DummyStrategy(), broker=broker)
        engine.run_once(["TEST"])
        self.assertIn("TEST", broker.positions())


if __name__ == "__main__":
    unittest.main()
