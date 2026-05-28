"""Unit tests for strategies/contracts.py"""
import unittest
import os
import json
from strategies.contracts import GridScalpStrategy


class TestGridScalpStrategy(unittest.TestCase):
    def setUp(self):
        self.cfg = {"grid_levels": 5, "grid_spacing_atr": 2.0,
                    "trend_filter": False, "position_pct": 0.05}
        self.gs = GridScalpStrategy(self.cfg)

    def tearDown(self):
        for f in ("grid_default.json", "grid_state.json"):
            if os.path.exists(f):
                os.remove(f)

    def test_name(self):
        self.assertEqual(self.gs.name, "grid_scalp")

    def test_on_bar_initializes_grid(self):
        result = self.gs.on_bar({"close": 100.0})
        self.assertIsInstance(result, list)

    def test_grid_builds_orders(self):
        self.gs._build_grid(100.0, 0.01, "both")
        self.assertGreater(len(self.gs._orders), 0)

    def test_grid_trend_long_only(self):
        self.gs._build_grid(100.0, 0.01, "long")
        for key, order in self.gs._orders.items():
            self.assertLess(order["price"], 100.0)
            self.assertEqual(order["side"], "BUY")

    def test_grid_trend_short_only(self):
        self.gs._build_grid(100.0, 0.01, "short")
        for key, order in self.gs._orders.items():
            self.assertGreater(order["price"], 100.0)
            self.assertEqual(order["side"], "SELL")

    def test_state_persistence(self):
        self.gs._mid_price = 95.0
        self.gs._build_grid(95.0, 0.01, "both")
        self.gs._save_state()
        self.assertTrue(os.path.exists("grid_default.json"))

        gs2 = GridScalpStrategy(self.cfg)
        self.assertEqual(gs2._mid_price, 95.0)

    def test_calc_atr_nonzero(self):
        self.gs._price_history = [100.0, 101.0, 102.0, 101.0, 100.0,
                                   101.0, 102.0, 103.0, 102.0, 101.0,
                                   100.0, 101.0, 102.0, 101.0, 100.0]
        atr = self.gs._calc_atr()
        self.assertGreater(atr, 0)


if __name__ == "__main__":
    unittest.main()
