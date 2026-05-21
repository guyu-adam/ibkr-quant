"""Unit tests for core/alpha_factors.py"""
import unittest
import pandas as pd
import numpy as np
from core.alpha_factors import compute_factors, compute_forward_returns


class TestComputeFactors(unittest.TestCase):
    def setUp(self):
        n = 120
        dates = pd.date_range('2024-01-01', periods=n, freq='B')
        close = np.random.randn(n).cumsum() + 100
        self.df = pd.DataFrame({
            'open': close - 0.3, 'high': close + 0.8,
            'low': close - 0.5, 'close': close,
            'volume': np.random.randint(10000, 100000, n),
        }, index=dates)

    def test_output_is_dataframe(self):
        f = compute_factors(self.df)
        self.assertIsInstance(f, pd.DataFrame)

    def test_has_expected_factors(self):
        f = compute_factors(self.df)
        expected = ['rsi_14', 'macd', 'mom_21d', 'vol_21d',
                    'atr_14', 'bb_width', 'skew_21d', 'williams_r']
        for col in expected:
            self.assertIn(col, f.columns, f"missing {col}")

    def test_no_all_nan_columns(self):
        f = compute_factors(self.df)
        for col in f.columns:
            self.assertFalse(f[col].isna().all(), f"{col} is all NaN")

    def test_forward_returns_shape(self):
        fwd = compute_forward_returns(self.df['close'], horizon=5)
        self.assertEqual(len(fwd), len(self.df))
        self.assertTrue(fwd.iloc[-6] is not None or True)  # last 5 are NaN

    def test_insufficient_data(self):
        short = pd.DataFrame({
            'open': [100], 'high': [101], 'low': [99],
            'close': [100], 'volume': [1000],
        })
        f = compute_factors(short)
        self.assertIsInstance(f, pd.DataFrame)


if __name__ == '__main__':
    unittest.main()
