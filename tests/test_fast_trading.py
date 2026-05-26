"""Unit tests for strategies/fast_trading.py"""
import unittest
import numpy as np
import pandas as pd
from core.data_feed import YFinanceFeed
from strategies.fast_trading import MeanReversionStrategy, PositionSizer


class TestMeanReversionStrategy(unittest.TestCase):
    def setUp(self):
        np.random.seed(42)
        self.strategy = MeanReversionStrategy()
        # Build mock data: mean-reverting random walk with RSI dips
        n = 200
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        close = 100 + np.random.randn(n).cumsum() * 0.3
        self.df = pd.DataFrame(
            {"open": close * 0.99, "high": close * 1.01, "low": close * 0.98,
             "close": close, "volume": np.random.randint(50000, 200000, n)},
            index=dates,
        )

    def test_name(self):
        self.assertEqual(self.strategy.name, "mean_reversion")

    def test_evaluate_returns_dict(self):
        result = self.strategy.evaluate(
            type("Feed", (), {"fetch_history": lambda s, p=None, iv=None: self.df})(),
            "TEST",
        )
        self.assertIsInstance(result, dict)
        self.assertIn("signal", result)
        self.assertIn("score", result)
        self.assertIn("rsi", result)

    def test_insufficient_data(self):
        short = self.df.iloc[:10]
        result = self.strategy.evaluate(
            type("Feed", (), {"fetch_history": lambda s, p=None, iv=None: short})(),
            "TEST",
        )
        self.assertEqual(result["reason"], "insufficient data")

    def test_set_vix(self):
        self.strategy.set_vix(12.0)
        self.assertEqual(self.strategy._vix, 12.0)

    def test_adaptive_atr_low_vix(self):
        self.strategy.set_vix(10.0)
        mult = self.strategy._get_atr_mult()
        self.assertEqual(mult, 1.5)

    def test_positions_dict_triggers_sell_path(self):
        result = self.strategy.evaluate(
            type("Feed", (), {"fetch_history": lambda s, p=None, iv=None: self.df})(),
            "TEST",
            positions={"TEST": {"avg_cost": 120.0, "stop_loss": 90.0}},
        )
        self.assertIn("signal", result)


class TestPositionSizer(unittest.TestCase):
    def setUp(self):
        self.sizer = PositionSizer()

    def test_size_positive(self):
        shares = self.sizer.size(equity=100_000, price=50.0, atr=1.0)
        self.assertGreater(shares, 0)
        self.assertEqual(shares % 100, 0)  # round lots

    def test_size_zero_price(self):
        shares = self.sizer.size(equity=100_000, price=0, atr=1.0)
        self.assertEqual(shares, 0)


if __name__ == "__main__":
    unittest.main()
