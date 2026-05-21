"""Unit tests for core/portfolio_optimizer.py"""
import unittest
import pandas as pd
import numpy as np
from core.portfolio_optimizer import optimize_portfolio


class TestOptimizePortfolio(unittest.TestCase):
    def setUp(self):
        np.random.seed(42)
        n = 120
        dates = pd.date_range('2024-01-01', periods=n, freq='B')
        self.symbols = ['A', 'B', 'C', 'D', 'E']
        data = {}
        for i, s in enumerate(self.symbols):
            data[s] = 100 + np.random.randn(n).cumsum() + i * 5
        self.prices = pd.DataFrame(data, index=dates)
        self.alpha = pd.Series(
            [0.03, 0.01, -0.01, 0.02, -0.02],
            index=self.symbols,
        )

    def test_equal_weight(self):
        w = optimize_portfolio(self.symbols, self.alpha, self.prices,
                               method='equal_weight')
        self.assertAlmostEqual(sum(w.values()), 1.0, places=2)
        self.assertEqual(len(w), 5)

    def test_risk_parity(self):
        w = optimize_portfolio(self.symbols, self.alpha, self.prices,
                               method='risk_parity')
        total = sum(w.values())
        self.assertGreater(total, 0.9)
        self.assertLess(total, 1.1)

    def test_min_variance(self):
        w = optimize_portfolio(self.symbols, self.alpha, self.prices,
                               method='min_variance')
        total = sum(w.values())
        self.assertGreater(total, 0.9)

    def test_max_sharpe(self):
        w = optimize_portfolio(self.symbols, self.alpha, self.prices,
                               method='max_sharpe')
        total = sum(w.values())
        self.assertGreater(total, 0.9)

    def test_empty_symbols(self):
        w = optimize_portfolio([], pd.Series(), pd.DataFrame())
        self.assertEqual(w, {})

    def test_single_symbol(self):
        w = optimize_portfolio(['A'], self.alpha, self.prices)
        self.assertEqual(w, {'A': 1.0})


if __name__ == '__main__':
    unittest.main()
