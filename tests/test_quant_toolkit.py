"""
Unit tests for quant_toolkit indicators and portfolio modules.
"""
import unittest
import pandas as pd
import numpy as np
from quant_toolkit.indicators import rsi, macd, ema, atr, bollinger_bands, obv
from quant_toolkit.portfolio import _validate


class TestQuantIndicators(unittest.TestCase):
    def setUp(self):
        n = 100
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        self.close = pd.Series(np.random.randn(n).cumsum() + 100, index=dates)
        self.high = self.close + np.random.uniform(0.5, 2.0, n)
        self.low = self.close - np.random.uniform(0.5, 2.0, n)
        self.volume = pd.Series(np.random.randint(10000, 100000, n), index=dates)

    def test_rsi_range(self):
        result = rsi(self.close, period=14)
        valid = result.dropna()
        self.assertTrue((valid >= 0).all())
        self.assertTrue((valid <= 100).all())

    def test_macd_columns(self):
        result = macd(self.close)
        for col in ["macd", "signal", "histogram"]:
            self.assertIn(col, result.columns)

    def test_macd_histogram_is_diff(self):
        result = macd(self.close)
        pd.testing.assert_series_equal(
            result["histogram"].dropna(),
            (result["macd"] - result["signal"]).dropna(),
            check_names=False,
        )

    def test_ema_length(self):
        result = ema(self.close, period=20)
        self.assertEqual(len(result), len(self.close))

    def test_atr_positive(self):
        result = atr(self.high, self.low, self.close, period=14)
        valid = result.dropna()
        self.assertTrue((valid >= 0).all())

    def test_bollinger_bands_columns(self):
        result = bollinger_bands(self.close)
        for col in ["upper", "middle", "lower", "bandwidth", "percent_b"]:
            self.assertIn(col, result.columns)

    def test_bollinger_upper_above_lower(self):
        result = bollinger_bands(self.close)
        valid = result.dropna()
        self.assertTrue((valid["upper"] >= valid["lower"]).all())

    def test_obv_length(self):
        result = obv(self.close, self.volume)
        self.assertEqual(len(result), len(self.close))


class TestPortfolioValidation(unittest.TestCase):
    def test_validate_too_few_rows(self):
        df = pd.DataFrame({"A": np.random.randn(10)}, index=pd.date_range("2024-01-01", periods=10))
        with self.assertRaises(ValueError):
            _validate(df)

    def test_validate_sufficient_rows(self):
        df = pd.DataFrame({"A": np.random.randn(50)}, index=pd.date_range("2024-01-01", periods=50))
        result = _validate(df)
        self.assertEqual(len(result), 50)

    def test_validate_drops_nan(self):
        data = np.random.randn(50)
        data[10] = np.nan
        data[20] = np.nan
        df = pd.DataFrame({"A": data}, index=pd.date_range("2024-01-01", periods=50))
        result = _validate(df)
        self.assertEqual(len(result), 48)


if __name__ == "__main__":
    unittest.main()
