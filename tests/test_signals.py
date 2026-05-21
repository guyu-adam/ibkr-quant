"""
Unit tests for strategy/signals.py
"""
import unittest
import pandas as pd
import numpy as np
from strategy.signals import ema, rsi, atr, compute_indicators, generate_signal


class TestEMA(unittest.TestCase):
    def setUp(self):
        self.close = pd.Series([10.0, 11.0, 12.0, 11.5, 12.5, 13.0, 12.0, 11.0, 10.5, 11.5])

    def test_ema_output_length(self):
        result = ema(self.close, period=5)
        self.assertEqual(len(result), len(self.close))

    def test_ema_no_nan_at_end(self):
        """EMA should produce a value for the last data point."""
        result = ema(self.close, period=3)
        self.assertFalse(pd.isna(result.iloc[-1]))

    def test_ema_monotonic_input(self):
        """EMA of strictly increasing series should be increasing."""
        increasing = pd.Series(range(1, 21), dtype=float)
        result = ema(increasing, period=5)
        self.assertTrue(result.iloc[-1] > result.iloc[5])

    def test_ema_constant_input(self):
        """EMA of constant series should equal the constant."""
        constant = pd.Series([5.0] * 50)
        result = ema(constant, period=10)
        pd.testing.assert_series_equal(
            result.iloc[20:], constant.iloc[20:], check_exact=False, rtol=1e-10
        )


class TestRSI(unittest.TestCase):
    def setUp(self):
        np.random.seed(42)
        self.close = pd.Series(np.random.randn(100).cumsum() + 100)

    def test_rsi_range(self):
        result = rsi(self.close, period=14)
        valid = result.dropna()
        self.assertTrue((valid >= 0).all() and (valid <= 100).all())

    def test_rsi_all_up(self):
        """RSI of a strictly increasing series should be near 100."""
        up = pd.Series(range(1, 101), dtype=float)
        result = rsi(up, period=14)
        self.assertGreater(result.iloc[-1], 95)

    def test_rsi_all_down(self):
        """RSI of a strictly decreasing series should be near 0."""
        down = pd.Series(range(100, 0, -1), dtype=float)
        result = rsi(down, period=14)
        self.assertLess(result.iloc[-1], 5)

    def test_rsi_returns_nan_for_insufficient_data(self):
        short = pd.Series([10.0, 11.0, 12.0])
        result = rsi(short, period=14)
        self.assertTrue(result.isna().all())


class TestATR(unittest.TestCase):
    def setUp(self):
        dates = pd.date_range("2024-01-01", periods=50, freq="D")
        self.df = pd.DataFrame({
            "open":  np.random.randn(50).cumsum() + 100,
            "high":  np.random.randn(50).cumsum() + 102,
            "low":   np.random.randn(50).cumsum() + 98,
            "close": np.random.randn(50).cumsum() + 100,
        }, index=dates)
        self.df["high"] = self.df[["open", "high", "low", "close"]].max(axis=1)
        self.df["low"] = self.df[["open", "high", "low", "close"]].min(axis=1)

    def test_atr_positive(self):
        result = atr(self.df, period=14)
        valid = result.dropna()
        self.assertTrue((valid > 0).all())

    def test_atr_output_length(self):
        result = atr(self.df, period=14)
        self.assertEqual(len(result), len(self.df))


class TestComputeIndicators(unittest.TestCase):
    def setUp(self):
        dates = pd.date_range("2024-01-01", periods=100, freq="5min")
        self.df = pd.DataFrame({
            "open":   np.random.randn(100).cumsum() + 100,
            "high":   np.random.randn(100).cumsum() + 103,
            "low":    np.random.randn(100).cumsum() + 97,
            "close":  np.random.randn(100).cumsum() + 100,
            "volume": np.random.randint(1000, 10000, 100),
        }, index=dates)
        self.df["high"] = self.df[["open", "close"]].max(axis=1) + 2
        self.df["low"] = self.df[["open", "close"]].min(axis=1) - 2

    def test_returns_all_columns(self):
        result = compute_indicators(self.df)
        for col in ["rsi", "ema_fast", "ema_slow", "atr", "momentum"]:
            self.assertIn(col, result.columns)

    def test_momentum_sign_consistent(self):
        """momentum column should reflect ema_fast - ema_slow."""
        result = compute_indicators(self.df)
        pd.testing.assert_series_equal(
            result["momentum"],
            result["ema_fast"] - result["ema_slow"],
            check_names=False,
        )

    def test_no_side_effect(self):
        """compute_indicators should not mutate input DataFrame."""
        original_cols = list(self.df.columns)
        compute_indicators(self.df)
        self.assertEqual(list(self.df.columns), original_cols)


class TestGenerateSignal(unittest.TestCase):
    def _make_df(self, close_series=None):
        """Helper to create a minimal DataFrame with required columns."""
        n = len(close_series) if close_series is not None else 100
        dates = pd.date_range("2024-01-01", periods=n, freq="5min")
        df = pd.DataFrame(index=dates)
        if close_series is not None:
            df["close"] = close_series
        else:
            df["close"] = np.random.randn(n).cumsum() + 100
        df["rsi"] = rsi(df["close"], 14)
        df["ema_fast"] = ema(df["close"], 10)
        df["ema_slow"] = ema(df["close"], 30)
        df["atr"] = pd.Series(np.random.uniform(0.5, 3.0, n), index=dates)
        df["momentum"] = df["ema_fast"] - df["ema_slow"]
        return df

    def test_signal_keys(self):
        df = self._make_df()
        sig = generate_signal(df)
        for key in ["signal", "price", "atr", "stop_long", "stop_short", "reason"]:
            self.assertIn(key, sig)

    def test_signal_value_range(self):
        df = self._make_df()
        sig = generate_signal(df)
        self.assertIn(sig["signal"], [-1, 0, 1])

    def test_long_stop_below_price(self):
        """Stop for long should be below current price."""
        df = self._make_df()
        sig = generate_signal(df)
        self.assertLess(sig["stop_long"], sig["price"])

    def test_short_stop_above_price(self):
        """Stop for short should be above current price."""
        df = self._make_df()
        sig = generate_signal(df)
        self.assertGreater(sig["stop_short"], sig["price"])

    def test_signal_0_when_rsi_neutral(self):
        """No signal when RSI is between oversold and overbought."""
        n = 50
        dates = pd.date_range("2024-01-01", periods=n, freq="5min")
        df = pd.DataFrame(index=dates)
        df["close"] = pd.Series(np.linspace(100, 110, n), index=dates)
        df["rsi"] = pd.Series([50.0] * n, index=dates)         # neutral RSI
        df["ema_fast"] = pd.Series(np.linspace(100, 112, n), index=dates)
        df["ema_slow"] = pd.Series(np.linspace(100, 108, n), index=dates)
        df["atr"] = pd.Series([1.0] * n, index=dates)
        df["momentum"] = df["ema_fast"] - df["ema_slow"]       # > 0 bullish
        sig = generate_signal(df)
        self.assertEqual(sig["signal"], 0)


if __name__ == "__main__":
    unittest.main()
