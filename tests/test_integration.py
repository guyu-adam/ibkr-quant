"""Integration test: BacktestBroker → MeanReversionStrategy → report."""
import unittest
import numpy as np
import pandas as pd
from core.backtest import BacktestEngine
from strategies.fast_trading import MeanReversionStrategy


class TestBacktestIntegration(unittest.TestCase):
    def setUp(self):
        np.random.seed(42)
        n = 252
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        close = 100 + np.random.randn(n).cumsum() * 0.5
        self.prices = pd.DataFrame({"SPY": close}, index=dates)

    def test_full_backtest_pipeline(self):
        engine = BacktestEngine(initial_equity=100_000, commission=0.001, slippage=0.0005)
        strategy = MeanReversionStrategy()
        report = engine.run(strategy, self.prices)

        self.assertIn("sharpe", report)
        self.assertIn("total_return", report)
        self.assertIn("max_drawdown", report)
        self.assertIn("win_rate", report)
        self.assertIn("profit_factor", report)
        self.assertIn("n_trades", report)
        self.assertIsInstance(report["sharpe"], float)
        self.assertIsInstance(report["n_trades"], int)

    def test_backtest_broker_positions(self):
        engine = BacktestEngine(initial_equity=100_000)
        engine.broker.set_prices({"TEST": 50.0})
        engine.broker.market_order("TEST", 100, "BUY")
        pos = engine.broker.positions()
        self.assertIn("TEST", pos)
        self.assertEqual(pos["TEST"], 100)

    def test_backtest_broker_sell(self):
        engine = BacktestEngine(initial_equity=100_000)
        engine.broker.set_prices({"TEST": 50.0})
        engine.broker.market_order("TEST", 100, "BUY")
        engine.broker.set_prices({"TEST": 55.0})
        engine.broker.market_order("TEST", 100, "SELL")
        pos = engine.broker.positions()
        self.assertNotIn("TEST", pos)


if __name__ == "__main__":
    unittest.main()
