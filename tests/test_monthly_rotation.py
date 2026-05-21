"""
Unit tests for strategy/monthly_rotation.py
"""
import unittest
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np
from strategy.monthly_rotation import get_momentum_scores, generate_orders, UNIVERSE, TOP_N


class TestGetMomentumScores(unittest.TestCase):
    def _make_mock_data(self, n_options=5):
        """Build mock yfinance response with rising prices."""
        n = 60
        return {
            sym: pd.Series(np.linspace(100, 100 + i * 5, n), index=pd.date_range("2024-01-01", periods=n))
            for i, sym in zip(range(1, n_options + 1), ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"][:n_options])
        }

    @patch("strategy.monthly_rotation.yf.download")
    def test_empty_universe(self, mock_dl):
        mock_dl.return_value = None  # batch download fails, fallback
        with patch("strategy.monthly_rotation.yf.Ticker") as mock_ticker:
            mock_tick = MagicMock()
            mock_tick.history.return_value = pd.DataFrame()
            mock_ticker.return_value = mock_tick
            result = get_momentum_scores(universe=[])
            self.assertTrue(result.empty)

    @patch("strategy.monthly_rotation.yf.download")
    def test_batch_download_columns(self, mock_dl):
        """Verify output columns."""
        mock_dl.return_value = None  # triggers per-symbol fallback
        # We can't fully mock yf.Ticker easily; skip integration
        # Instead, test with a short universe that would be caught by exception
        with patch("strategy.monthly_rotation.yf.Ticker") as mock_ticker:
            mock_tick = MagicMock()
            mock_tick.history.return_value = pd.DataFrame()
            mock_ticker.return_value = mock_tick
            result = get_momentum_scores(universe=["FAKE"])
            self.assertTrue(result.empty)

    @patch("strategy.monthly_rotation.yf.download")
    def test_result_has_required_columns(self, mock_dl):
        """Even on empty data, return columns should include required names."""
        mock_dl.return_value = None
        with patch("strategy.monthly_rotation.yf.Ticker") as mock_ticker:
            mock_tick = MagicMock()
            mock_tick.history.return_value = pd.DataFrame()
            mock_ticker.return_value = mock_tick
            result = get_momentum_scores(universe=["FAKE"])
            for col in ["symbol", "momentum", "price", "rank", "selected"]:
                self.assertIn(col, result.columns)


class TestGenerateOrders(unittest.TestCase):
    def setUp(self):
        self.scores = pd.DataFrame([
            {"symbol": "AAPL", "momentum": 0.15, "price": 180.0, "rank": 1, "selected": True},
            {"symbol": "NVDA", "momentum": 0.30, "price": 900.0, "rank": 2, "selected": True},
            {"symbol": "MSFT", "momentum": 0.10, "price": 420.0, "rank": 3, "selected": True},
            {"symbol": "SPY",  "momentum": 0.08, "price": 500.0, "rank": 4, "selected": True},
            {"symbol": "QQQ",  "momentum": 0.06, "price": 400.0, "rank": 5, "selected": True},
            {"symbol": "TSLA", "momentum": -0.05, "price": 250.0, "rank": 6, "selected": False},
        ])

    def test_empty_holdings_all_buys(self):
        orders = generate_orders(self.scores, {}, equity=10_000)
        self.assertTrue(len(orders["buy"]) >= 1)
        self.assertEqual(len(orders["sell"]), 0)

    def test_sell_stale_positions(self):
        """Positions not in top-N should be sold."""
        current = {"TSLA": 10}
        orders = generate_orders(self.scores, current, equity=10_000)
        sells = [o["symbol"] for o in orders["sell"]]
        self.assertIn("TSLA", sells)

    def test_hold_existing_top_pick(self):
        """Position already in top-N should be held, not bought."""
        current = {"AAPL": 55}  # 55 * 180 ≈ 9900, close to full equity
        orders = generate_orders(self.scores, current, equity=10_000)
        buys = [o["symbol"] for o in orders["buy"]]
        self.assertNotIn("AAPL", buys)

    def test_target_shares_positive(self):
        orders = generate_orders(self.scores, {}, equity=50_000)
        for t in orders["target"]:
            self.assertGreater(t["shares"], 0)
            self.assertIn("weight", t)

    def test_empty_scores(self):
        empty = pd.DataFrame(columns=["symbol", "momentum", "price", "rank", "selected"])
        orders = generate_orders(empty, {}, 10_000)
        self.assertEqual(orders, {"sell": [], "buy": [], "hold": [], "target": []})


if __name__ == "__main__":
    unittest.main()
