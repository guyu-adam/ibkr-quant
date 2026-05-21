"""
Unit tests using a mocked IBKR broker to verify broker-dependent logic.
"""
import unittest
from unittest.mock import MagicMock, patch, PropertyMock
import pandas as pd
import numpy as np
from core.risk import RiskManager
from strategy.legacy.signals import compute_indicators, generate_signal


class TestRiskManagerWithMockBroker(unittest.TestCase):
    """Integration-ish tests: RiskManager + mock broker."""

    def setUp(self):
        self.broker = MagicMock()
        self.broker.net_liquidation.return_value = 50_000.0
        self.broker.daily_pnl.return_value = 200.0
        self.broker.positions.return_value = {}
        self.rm = RiskManager(self.broker)

    def test_consecutive_approvals(self):
        """Multiple approvals within limits should all pass."""
        self.broker.last_price.return_value = 50.0
        for _ in range(5):
            result = self.rm.approve("TEST", 100, 50.0)
            self.assertTrue(result)

    def test_daily_loss_halts_all_further_trades(self):
        """Once daily loss is hit, all subsequent approvals fail."""
        self.broker.daily_pnl.return_value = -2000.0   # -4% > 2% limit
        self.broker.last_price.return_value = 50.0
        result1 = self.rm.approve("A", 10, 50.0)
        self.assertFalse(result1)
        result2 = self.rm.approve("B", 10, 50.0)
        self.assertFalse(result2)

    def test_exposure_tracks_new_positions(self):
        """Exposure check should account for pending trade value."""
        # 80% of 50000 = 40000
        self.broker.last_price.return_value = 200.0
        # First trade: 100 shares @ 200 = 20000 → OK
        self.assertTrue(self.rm.approve("X", 100, 200.0))
        # Simulate position update after first trade
        self.broker.positions.return_value = {"X": 100}
        # Second: another 150 shares @ 200 = 30000, total = 50000 > 40000 → FAIL
        self.assertFalse(self.rm.approve("Y", 150, 200.0))

    def test_position_size_zero_equity(self):
        """position_size with zero equity should return 0."""
        self.broker.net_liquidation.return_value = 0.0
        shares = self.rm.position_size(price=100.0, atr=2.0)
        self.assertEqual(shares, 0)


class TestSignalPipeline(unittest.TestCase):
    """End-to-end test: raw data → indicators → signal."""

    def _make_uptrend_data(self) -> pd.DataFrame:
        """Generate a DataFrame with a clear uptrend (close price rising steadily)."""
        n = 60
        dates = pd.date_range("2024-06-01", periods=n, freq="5min")
        df = pd.DataFrame(index=dates)
        close = np.linspace(100, 130, n) + np.random.randn(n) * 0.5
        df["close"] = close
        df["open"] = close - np.random.uniform(0, 0.3, n)
        df["high"] = close + np.random.uniform(0.3, 0.8, n)
        df["low"] = close - np.random.uniform(0.3, 0.8, n)
        df["volume"] = np.random.randint(5000, 50000, n)
        return df

    def _make_downtrend_data(self) -> pd.DataFrame:
        """Generate a DataFrame with a clear downtrend."""
        n = 60
        dates = pd.date_range("2024-06-01", periods=n, freq="5min")
        df = pd.DataFrame(index=dates)
        close = np.linspace(130, 100, n) + np.random.randn(n) * 0.5
        df["close"] = close
        df["open"] = close + np.random.uniform(0, 0.3, n)
        df["high"] = close + np.random.uniform(0.3, 0.8, n)
        df["low"] = close - np.random.uniform(0.3, 0.8, n)
        df["volume"] = np.random.randint(5000, 50000, n)
        return df

    def test_pipeline_output_structure(self):
        df = self._make_uptrend_data()
        df = compute_indicators(df)
        sig = generate_signal(df)
        self.assertIsNotNone(sig["price"])
        self.assertIsNotNone(sig["atr"])
        self.assertGreater(sig["atr"], 0)

    def test_pipeline_preserves_original_columns(self):
        df = self._make_uptrend_data()
        orig_cols = set(df.columns)
        df_result = compute_indicators(df)
        for col in orig_cols:
            self.assertIn(col, df_result.columns)


if __name__ == "__main__":
    unittest.main()
