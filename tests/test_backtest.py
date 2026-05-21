"""
Unit tests for strategy/backtest.py
"""
import unittest
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np
from strategy.legacy.backtest import run_backtest, _max_drawdown


class TestMaxDrawdown(unittest.TestCase):
    def test_no_drawdown(self):
        self.assertEqual(_max_drawdown([100, 101, 102, 103]), 0.0)

    def test_simple_drawdown(self):
        self.assertAlmostEqual(_max_drawdown([100, 90, 100]), -0.1)

    def test_multiple_drawdowns(self):
        # peak 100, drops to 80 (-20%), recovers to 100, drops to 70 (-30%)
        self.assertAlmostEqual(_max_drawdown([100, 80, 100, 70]), -0.3)

    def test_flat_curve(self):
        self.assertEqual(_max_drawdown([100] * 10), 0.0)


class TestRunBacktest(unittest.TestCase):
    @patch("strategy.legacy.backtest.yf.download")
    def test_empty_data_returns_empty(self, mock_download):
        mock_download.return_value = pd.DataFrame()
        result = run_backtest("FAKE")
        self.assertEqual(result, {})

    @patch("strategy.legacy.backtest.yf.download")
    def test_result_keys(self, mock_download):
        """Verify all expected keys are in the result dict."""
        dates = pd.date_range("2023-01-01", periods=200, freq="B")
        mock_download.return_value = pd.DataFrame({
            "Open":   np.random.randn(200).cumsum() + 100,
            "High":   np.random.randn(200).cumsum() + 103,
            "Low":    np.random.randn(200).cumsum() + 97,
            "Close":  np.random.randn(200).cumsum() + 100,
            "Volume": np.random.randint(1000, 10000, 200),
        }, index=dates)

        result = run_backtest("TEST")
        for key in ["symbol", "total_trades", "win_rate", "final_equity",
                     "total_return", "sharpe", "max_drawdown", "equity_curve"]:
            self.assertIn(key, result)

    @patch("strategy.legacy.backtest.yf.download")
    def test_no_trades_scenario(self, mock_download):
        """No triggers: RSI stays neutral (~50), no signals should fire."""
        n = 200
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        # Flat price → RSI stays around 50 → no signals
        mock_download.return_value = pd.DataFrame({
            "Open":   [100.0] * n,
            "High":   [100.5] * n,
            "Low":    [99.5] * n,
            "Close":  [100.0] * n,
            "Volume": [10000] * n,
        }, index=dates)

        result = run_backtest("FLAT")
        self.assertEqual(result["total_trades"], 0)
        self.assertEqual(result["final_equity"], 10_000.0)

    @patch("strategy.legacy.backtest.yf.download")
    def test_equity_curve_length(self, mock_download):
        """Equity curve should have length = len(data) + 1 (initial value)."""
        n = 100
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        close = np.linspace(100, 100, n)  # flat
        mock_download.return_value = pd.DataFrame({
            "Open":   close,
            "High":   close + 1,
            "Low":    close - 1,
            "Close":  close,
            "Volume": [10000] * n,
        }, index=dates)

        result = run_backtest("TEST")
        self.assertEqual(len(result["equity_curve"]), n + 1)

    @patch("strategy.legacy.backtest.yf.download")
    def test_win_rate_in_range(self, mock_download):
        n = 200
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        close = np.random.randn(n).cumsum() + 100
        mock_download.return_value = pd.DataFrame({
            "Open":   close - 0.5,
            "High":   close + 1,
            "Low":    close - 1,
            "Close":  close,
            "Volume": [10000] * n,
        }, index=dates)

        result = run_backtest("TEST")
        if result["total_trades"] > 0:
            self.assertGreaterEqual(result["win_rate"], 0.0)
            self.assertLessEqual(result["win_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
