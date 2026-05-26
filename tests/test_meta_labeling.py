"""Unit tests for core/meta_labeling.py"""
import unittest
import numpy as np
from core.meta_labeling import MetaLabeler


class TestMetaLabeler(unittest.TestCase):
    def setUp(self):
        self.ml = MetaLabeler(confidence=0.6)
        self.features = {"rsi": 35.0, "atr": 2.5, "volume_ratio": 1.2}

    def test_filter_signal_untrained_allows(self):
        result = self.ml.filter_signal(self.features)
        self.assertTrue(result)

    def test_record_trade_increments(self):
        self.ml.record_trade(self.features, 100.0)
        self.assertEqual(len(self.ml._y), 1)
        self.assertEqual(self.ml._y[0], 1)

    def test_record_trade_loss(self):
        self.ml.record_trade(self.features, -50.0)
        self.assertEqual(self.ml._y[0], 0)

    def test_dimension_mismatch_silently_skipped(self):
        self.ml.record_trade(self.features, 100.0)
        self.ml.record_trade({"rsi": 35.0}, 100.0)  # different dims → skipped
        self.assertEqual(len(self.ml._y), 1)

    def test_not_enough_samples_returns_true(self):
        for _ in range(50):
            self.ml.record_trade(self.features, 50.0 if _ % 2 == 0 else -30.0)
        result = self.ml.filter_signal(self.features)
        self.assertTrue(result)  # not enough for training yet


if __name__ == "__main__":
    unittest.main()
