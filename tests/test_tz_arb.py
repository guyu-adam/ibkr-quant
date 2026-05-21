"""
Unit tests for strategy/tz_arb.py — signal computation only.
"""
import unittest
from unittest.mock import patch
import pandas as pd
import numpy as np
from strategy.legacy.tz_arb import compute_signals, ADR_PAIRS


class TestComputeSignals(unittest.TestCase):
    @patch("strategy.legacy.tz_arb._get_close")
    def test_no_signal_below_threshold(self, mock_get_close):
        """ADR move below threshold should produce no signal."""
        close_data = pd.Series([100.0, 101.0], index=pd.DatetimeIndex([
            "2024-06-01", "2024-06-02"
        ]))
        mock_get_close.return_value = close_data
        signals = compute_signals(threshold=0.05)  # 5% threshold, 1% move → no signal
        self.assertEqual(len(signals), 0)

    @patch("strategy.legacy.tz_arb._get_close")
    def test_signal_above_threshold(self, mock_get_close):
        """ADR move above threshold should produce signal."""
        close_data = pd.Series([100.0, 104.0], index=pd.DatetimeIndex([
            "2024-06-01", "2024-06-02"
        ]))
        mock_get_close.return_value = close_data
        signals = compute_signals(threshold=0.02)
        # Should get 1 signal per ADR pair (7 pairs)
        self.assertGreater(len(signals), 0)
        for s in signals:
            self.assertIn("hk_code", s)
            self.assertIn("adr", s)
            self.assertIn("signal", s)
            self.assertIn("adr_move", s)

    @patch("strategy.legacy.tz_arb._get_close")
    def test_signal_direction_long(self, mock_get_close):
        """Positive ADR move should generate long signal (+1)."""
        close_data = pd.Series([100.0, 105.0], index=pd.DatetimeIndex([
            "2024-06-01", "2024-06-02"
        ]))
        mock_get_close.return_value = close_data
        signals = compute_signals(threshold=0.02)
        for s in signals:
            self.assertEqual(s["signal"], 1)

    @patch("strategy.legacy.tz_arb._get_close")
    def test_signal_direction_short(self, mock_get_close):
        """Negative ADR move should generate short signal (-1)."""
        close_data = pd.Series([100.0, 95.0], index=pd.DatetimeIndex([
            "2024-06-01", "2024-06-02"
        ]))
        mock_get_close.return_value = close_data
        signals = compute_signals(threshold=0.02)
        for s in signals:
            self.assertEqual(s["signal"], -1)

    @patch("strategy.legacy.tz_arb._get_close")
    def test_empty_data_graceful(self, mock_get_close):
        """Missing data for all pairs should return empty list, not crash."""
        mock_get_close.return_value = None
        signals = compute_signals()
        self.assertEqual(signals, [])

    def test_adr_pairs_format(self):
        """All ADR keys should be valid US tickers, all values should be .HK tickers."""
        for us, hk in ADR_PAIRS.items():
            self.assertFalse(hk.startswith("$"))
            self.assertTrue(hk.endswith(".HK"))
            self.assertNotIn(" ", us)


if __name__ == "__main__":
    unittest.main()
