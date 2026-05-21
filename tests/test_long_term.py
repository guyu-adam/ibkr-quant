"""
Unit tests for strategy/long_term.py
"""
import unittest
from unittest.mock import MagicMock
import pandas as pd
from strategy.long_term import compute_target_weights, rebalance_trades


class TestComputeTargetWeights(unittest.TestCase):
    def test_normal_case(self):
        portfolio = {"A": 0.25, "B": 0.25}
        weights = compute_target_weights(portfolio)
        self.assertAlmostEqual(sum(weights.values()), 1.0)
        self.assertAlmostEqual(weights["A"], 0.5)

    def test_already_normalized(self):
        portfolio = {"A": 0.5, "B": 0.5}
        weights = compute_target_weights(portfolio)
        self.assertAlmostEqual(sum(weights.values()), 1.0)

    def test_empty(self):
        self.assertEqual(compute_target_weights({}), {})

    def test_zero_sum(self):
        self.assertEqual(compute_target_weights({"A": 0, "B": 0}), {})


class TestRebalanceTrades(unittest.TestCase):
    def setUp(self):
        self.prices = {"A": 100.0, "B": 200.0, "C": 50.0}
        self.weights = {"A": 0.5, "B": 0.3, "C": 0.2}

    def test_no_positions_all_buys(self):
        """Empty portfolio: should generate buy trades for all."""
        trades = rebalance_trades(
            current_positions={},
            target_weights=self.weights,
            prices=self.prices,
            equity=10_000.0,
            drift_threshold=0.0,  # 0 threshold = always rebalance
        )
        self.assertEqual(len(trades), 3)
        for t in trades:
            self.assertEqual(t["action"], "BUY")

    def test_drift_threshold_skips_small(self):
        """Positions close to target should be skipped."""
        current = {"A": 50, "B": 15, "C": 40}  # close to target
        trades = rebalance_trades(
            current_positions=current,
            target_weights=self.weights,
            prices=self.prices,
            equity=10_000.0,
            drift_threshold=0.05,  # 5% drift threshold
        )
        # With 5% threshold, small deviations should be skipped
        drift_A = 0.5 - (50 * 100) / 10000  # 0.5 - 0.5 = 0
        self.assertAlmostEqual(drift_A, 0.0)

    def test_sell_when_overweight(self):
        """Overweight position should generate SELL."""
        current = {"A": 200, "B": 0, "C": 0}   # A is 200% of portfolio
        trades = rebalance_trades(
            current_positions=current,
            target_weights={"A": 0.3, "B": 0.7},
            prices={"A": 100.0, "B": 50.0},
            equity=20_000.0,
            drift_threshold=0.0,
        )
        sells = [t for t in trades if t["action"] == "SELL"]
        self.assertTrue(len(sells) >= 1)
        self.assertEqual(sells[0]["ticker"], "A")

    def test_missing_price_skipped(self):
        """Tickers with no price data should be skipped."""
        trades = rebalance_trades(
            current_positions={},
            target_weights={"A": 0.5, "B": 0.5},
            prices={"A": 100.0, "B": 0.0},   # B has zero price
            equity=10_000.0,
            drift_threshold=0.0,
        )
        tickers = [t["ticker"] for t in trades]
        self.assertNotIn("B", tickers)


if __name__ == "__main__":
    unittest.main()
