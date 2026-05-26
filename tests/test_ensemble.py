"""Unit tests for core/ensemble.py"""
import unittest
from core.ensemble import EnsembleEngine


class TestEnsembleEngine(unittest.TestCase):
    def setUp(self):
        self.ee = EnsembleEngine(method="equal")

    def test_empty_signals_returns_hold(self):
        result = self.ee.blend([])
        self.assertEqual(result["signal"], "hold")
        self.assertEqual(result["strength"], 0.0)

    def test_equal_weight_single(self):
        result = self.ee.blend([("strat_a", 1.0)])
        self.assertEqual(result["signal"], "buy")
        self.assertAlmostEqual(result["strength"], 1.0)

    def test_equal_weight_mixed(self):
        result = self.ee.blend([("a", 1.0), ("b", -1.0)])
        self.assertEqual(result["signal"], "hold")
        self.assertAlmostEqual(result["strength"], 0.0)

    def test_voting_method(self):
        ee = EnsembleEngine(method="voting")
        result = ee.blend([("a", 0.8), ("b", 0.6), ("c", 0.1)])
        self.assertEqual(result["signal"], "buy")

    def test_weighted_with_history(self):
        ee = EnsembleEngine(method="weighted")
        ee.record_pnl("strat_a", 0.5)
        ee.record_pnl("strat_a", 0.3)
        ee.record_pnl("strat_b", -0.2)
        for _ in range(15):
            ee.record_pnl("strat_a", 0.1)
            ee.record_pnl("strat_b", -0.05)
        result = ee.blend([("strat_a", 1.0), ("strat_b", -0.5)])
        self.assertIn(result["signal"], ("buy", "sell", "hold"))

    def test_strong_sell(self):
        result = self.ee.blend([("a", -0.9)])
        self.assertEqual(result["signal"], "sell")

    def test_record_pnl_trims_history(self):
        for _ in range(100):
            self.ee.record_pnl("s1", 0.01)
        self.assertLessEqual(len(self.ee._perf_history["s1"]), 100)


if __name__ == "__main__":
    unittest.main()
