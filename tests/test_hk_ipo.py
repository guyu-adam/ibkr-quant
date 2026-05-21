"""
Unit tests for strategy/hk_ipo.py — bracket order logic and scraping helpers.
"""
import unittest
from unittest.mock import MagicMock, patch
from strategy.legacy.hk_ipo import (
    fetch_listing_today, fetch_grey_premium,
    place_ipo_trade, HKIPOStrategy, _bracket_order,
)


class TestFetchListingToday(unittest.TestCase):
    @patch("strategy.legacy.hk_ipo.requests.get")
    def test_network_failure_graceful(self, mock_get):
        """Network failure should return empty list, not crash."""
        mock_get.side_effect = ConnectionError("timeout")
        result = fetch_listing_today()
        self.assertEqual(result, [])

    @patch("strategy.legacy.hk_ipo.requests.get")
    def test_empty_response(self, mock_get):
        """Empty HTML should return empty list."""
        mock_resp = MagicMock()
        mock_resp.text = "<html></html>"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        result = fetch_listing_today()
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)


class TestFetchGreyPremium(unittest.TestCase):
    @patch("strategy.legacy.hk_ipo.requests.get")
    def test_network_failure_returns_none(self, mock_get):
        mock_get.side_effect = ConnectionError("timeout")
        result = fetch_grey_premium("9988")
        self.assertIsNone(result)

    @patch("strategy.legacy.hk_ipo.requests.get")
    def test_no_match_returns_none(self, mock_get):
        """No matching code in HTML should return None."""
        mock_resp = MagicMock()
        mock_resp.text = "<html><tr><td>0001</td><td>Some Stock</td><td>1.00</td><td>+20</td></tr></html>"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        result = fetch_grey_premium("9988")
        self.assertIsNone(result)


class TestHKIPOStrategy(unittest.TestCase):
    def setUp(self):
        self.broker = MagicMock()
        self.broker.net_liquidation.return_value = 100_000.0
        self.risk_mgr = MagicMock()
        self.risk_mgr.approve.return_value = True
        self.ipo = HKIPOStrategy(self.broker, self.risk_mgr)

    @patch("strategy.legacy.hk_ipo.fetch_listing_today")
    def test_no_listings(self, mock_list):
        mock_list.return_value = []
        self.ipo.run()  # should not crash
        self.assertEqual(len(self.ipo._active), 0)

    @patch("strategy.legacy.hk_ipo.fetch_grey_premium")
    @patch("strategy.legacy.hk_ipo.fetch_listing_today")
    def test_listing_no_grey_premium(self, mock_list, mock_grey):
        mock_list.return_value = [{"code": "9988", "name": "TestCo", "ipo_price": 68.0}]
        mock_grey.return_value = None
        self.ipo.run()
        self.assertEqual(len(self.ipo._active), 0)

    @patch("strategy.legacy.hk_ipo.fetch_grey_premium")
    @patch("strategy.legacy.hk_ipo.fetch_listing_today")
    def test_listing_below_threshold(self, mock_list, mock_grey):
        """Grey premium below min threshold should skip."""
        mock_list.return_value = [{"code": "9988", "name": "TestCo", "ipo_price": 68.0}]
        mock_grey.return_value = 0.10  # below 0.15 min
        self.ipo.run()
        self.assertEqual(len(self.ipo._active), 0)

    def test_close_all_empty(self):
        """close_all with no positions should not crash."""
        self.ipo.close_all()
        self.ipo._active.clear()

    def test_close_all_with_positions(self):
        """close_all should attempt to sell existing IPO positions."""
        self.ipo._active = {"9988": MagicMock()}
        self.broker.positions.return_value = {"9988": 100}
        self.ipo.close_all()
        self.broker.market_order.assert_called()

    def test_default_config_applied(self):
        self.assertEqual(self.ipo.cfg["min_grey_premium"], 0.15)
        self.assertEqual(self.ipo.cfg["stop_pct"], 0.05)
        self.assertEqual(self.ipo.cfg["max_concurrent_positions"], 2)

    def test_custom_config_merged(self):
        ipo = HKIPOStrategy(self.broker, self.risk_mgr, {"min_grey_premium": 0.25})
        self.assertEqual(ipo.cfg["min_grey_premium"], 0.25)
        self.assertEqual(ipo.cfg["stop_pct"], 0.05)  # default retained


class TestPlaceIPOTrade(unittest.TestCase):
    def setUp(self):
        self.broker = MagicMock()
        self.broker.net_liquidation.return_value = 100_000.0
        self.risk_mgr = MagicMock()
        self.risk_mgr.approve.return_value = True
        self.cfg = {
            "min_grey_premium": 0.15, "stop_pct": 0.05,
            "target_pct_of_premium": 0.60, "max_risk_per_trade": 0.015,
        }

    def test_below_threshold_skipped(self):
        result = place_ipo_trade(self.broker, self.risk_mgr, "9988",
                                  68.0, 0.10, self.cfg)
        self.assertIsNone(result)

    def test_zero_shares_skipped(self):
        """Very low equity should result in 0 shares → skip."""
        self.broker.net_liquidation.return_value = 100.0
        result = place_ipo_trade(self.broker, self.risk_mgr, "9988",
                                  68.0, 0.30, self.cfg)
        self.assertIsNone(result)

    def test_risk_denied(self):
        """When risk manager denies, trade should be skipped."""
        self.risk_mgr.approve.return_value = False
        result = place_ipo_trade(self.broker, self.risk_mgr, "9988",
                                  68.0, 0.30, self.cfg)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
