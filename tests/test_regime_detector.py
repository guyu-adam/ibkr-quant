"""Unit tests for core/regime_detector.py"""
import unittest
import numpy as np
import pandas as pd
from core.regime_detector import RegimeDetector


class TestRegimeDetector(unittest.TestCase):
    def setUp(self):
        np.random.seed(42)
        n = 300
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        # Generate trending-up data
        close = 100 + np.arange(n) * 0.1 + np.random.randn(n).cumsum() * 0.5
        self.df = pd.DataFrame(
            {"open": close * 0.99, "high": close * 1.02, "low": close * 0.98,
             "close": close, "volume": np.random.randint(50000, 200000, n)},
            index=dates,
        )

    def test_initial_state(self):
        rd = RegimeDetector()
        self.assertEqual(rd._last_regime, 0)
        self.assertIsNone(rd._model)

    def test_fit_predict_returns_int(self):
        rd = RegimeDetector()
        regime = rd.fit_predict(self.df)
        self.assertIsInstance(regime, int)
        self.assertIn(regime, (0, 1, 2))

    def test_insufficient_data_returns_last(self):
        rd = RegimeDetector()
        short = self.df.iloc[:30]
        regime = rd.fit_predict(short)
        self.assertEqual(regime, 0)  # default

    def test_convenience_methods(self):
        rd = RegimeDetector()
        rd._last_regime = 0
        self.assertTrue(rd.is_trending_up())
        self.assertFalse(rd.is_mean_reverting())
        rd._last_regime = 1
        self.assertTrue(rd.is_mean_reverting())
        rd._last_regime = 2
        self.assertTrue(rd.is_trending_down())


if __name__ == "__main__":
    unittest.main()
