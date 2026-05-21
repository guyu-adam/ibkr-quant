"""Unit tests for core/ml_model.py"""
import unittest
import pandas as pd
import numpy as np
from core.ml_model import AlphaModel


class TestAlphaModel(unittest.TestCase):
    def setUp(self):
        np.random.seed(42)
        n = 200
        self.X = pd.DataFrame(
            np.random.randn(n, 5),
            columns=['f1', 'f2', 'f3', 'f4', 'f5'],
            index=pd.date_range('2024-01-01', periods=n, freq='B'),
        )
        self.y = pd.Series(
            np.random.randn(n) * 0.02,
            index=self.X.index,
        )

    def test_train_with_ridge(self):
        m = AlphaModel({'horizon': 5, 'min_train_days': 100})
        m.train(self.X, self.y)
        self.assertTrue(m.is_trained)

    def test_predict_returns_series(self):
        m = AlphaModel({'horizon': 5, 'min_train_days': 100})
        m.train(self.X.iloc[:150], self.y.iloc[:150])
        preds = m.predict(self.X.iloc[150:])
        self.assertIsInstance(preds, pd.Series)
        self.assertEqual(len(preds), 50)

    def test_select_top_returns_lists(self):
        m = AlphaModel({'horizon': 5, 'top_k': 5, 'bottom_k': 3, 'min_train_days': 100})
        m.train(self.X, self.y)
        preds = m.predict(self.X)
        longs, shorts = m.select_top(preds)
        self.assertEqual(len(longs), 5)
        self.assertEqual(len(shorts), 3)

    def test_untrained_predict_zeros(self):
        m = AlphaModel()
        preds = m.predict(self.X)
        self.assertTrue((preds == 0).all())

    def test_insufficient_data(self):
        m = AlphaModel({'min_train_days': 9999})
        m.train(self.X, self.y)
        self.assertFalse(m.is_trained)


if __name__ == '__main__':
    unittest.main()
