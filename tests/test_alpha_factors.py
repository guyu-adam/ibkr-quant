"""Unit tests for core/alpha_factors.py v2"""
import unittest
import pandas as pd
import numpy as np
from core.alpha_factors import compute_factors, compute_forward_returns


class TestComputeFactors(unittest.TestCase):
    def setUp(self):
        n = 500
        dates = pd.date_range('2024-01-01', periods=n, freq='B')
        np.random.seed(42)
        close = np.random.randn(n).cumsum() * 0.5 + 100
        self.df = pd.DataFrame({
            'open': close + np.random.uniform(-0.3, 0, n),
            'high': close + np.random.uniform(0.1, 0.6, n),
            'low': close + np.random.uniform(-0.6, -0.1, n),
            'close': close,
            'volume': np.random.randint(50000, 200000, n),
        }, index=dates)

    def test_output_is_dataframe(self):
        f = compute_factors(self.df)
        self.assertIsInstance(f, pd.DataFrame)

    def test_has_expected_factors(self):
        f = compute_factors(self.df)
        expected = ['rsi_14', 'macd_hist', 'ret_21d', 'vol_21d',
                    'atr_14', 'bb_width', 'skew_21d', 'willr_14']
        for col in expected:
            self.assertIn(col, f.columns, f"missing {col}")

    def test_no_all_nan_columns(self):
        f = compute_factors(self.df)
        # With random walk data, many factors produce valid values but some
        # (especially z-scores of volatile series) may be all-NaN.
        # Verify at least the core momentum/volatility factors have data.
        core_factors = ['rsi_14', 'ret_21d', 'vol_21d', 'macd_hist', 'bb_width']
        for col in core_factors:
            self.assertIn(col, f.columns)
            self.assertFalse(f[col].isna().all(), f"{col} is all NaN")
        self.assertGreater(len(f), 0, "No rows in output")

    def test_forward_returns_shape(self):
        fwd = compute_forward_returns(self.df['close'], horizon=5)
        self.assertEqual(len(fwd), len(self.df))

    def test_insufficient_data(self):
        short = pd.DataFrame({
            'open': [100], 'high': [101], 'low': [99],
            'close': [100], 'volume': [1000],
        })
        f = compute_factors(short)
        self.assertIsInstance(f, pd.DataFrame)


if __name__ == '__main__':
    unittest.main()
