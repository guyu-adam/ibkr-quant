"""
Unit tests for core/risk.py
"""
import unittest
from unittest.mock import MagicMock, patch
from core.risk import RiskManager


class TestRiskManager(unittest.TestCase):
    def setUp(self):
        self.mock_broker = MagicMock()
        self.mock_broker.net_liquidation.return_value = 100_000.0
        self.mock_broker.daily_pnl.return_value = 500.0
        self.mock_broker.positions.return_value = {}
        self.rm = RiskManager(self.mock_broker)

    # ── position_size ──────────────────────────────────────────────────────────
    def test_position_size_positive(self):
        shares = self.rm.position_size(price=150.0, atr=3.0)
        # risk_amt = 100000 * 0.01 = 1000
        # stop_dist = 3.0 * 2.0 = 6.0
        # shares = min(int(1000/6), int(100000*0.1/150)) = min(166, 66) = 66
        self.assertEqual(shares, 66)

    def test_position_size_zero_atr(self):
        shares = self.rm.position_size(price=100.0, atr=0.0)
        self.assertEqual(shares, 0)

    def test_position_size_negative_atr(self):
        shares = self.rm.position_size(price=100.0, atr=-1.0)
        self.assertEqual(shares, 0)

    def test_position_size_high_price_limits_shares(self):
        """Very high price should be constrained by MAX_POSITION_PCT."""
        shares = self.rm.position_size(price=50_000.0, atr=500.0)
        # risk_amt = 1000, stop_dist = 1000 → 1 share
        # max_shares = 100000 * 0.1 / 50000 = 0.2 → 0
        self.assertEqual(shares, 0)

    # ── approve ────────────────────────────────────────────────────────────────
    def test_approve_normal(self):
        self.mock_broker.last_price.return_value = 100.0
        result = self.rm.approve("AAPL", 100, 150.0)
        self.assertTrue(result)

    def test_approve_halted(self):
        self.rm._halted = True
        result = self.rm.approve("AAPL", 100, 150.0)
        self.assertFalse(result)

    def test_approve_daily_loss_trigger(self):
        self.mock_broker.daily_pnl.return_value = -3000.0   # -3% > 2% limit
        self.mock_broker.last_price.return_value = 100.0
        result = self.rm.approve("AAPL", 100, 150.0)
        self.assertFalse(result)
        self.assertTrue(self.rm._halted)

    def test_approve_total_exposure_limit(self):
        # Existing position: 800 shares @ $100 = $80,000 exposure
        self.mock_broker.positions.return_value = {"SPY": 800}
        self.mock_broker.last_price.return_value = 100.0
        # new exposure = 80000 + (100 * 150) = 95000 > 100000 * 0.8 = 80000
        result = self.rm.approve("AAPL", 100, 150.0)
        self.assertFalse(result)

    def test_approve_exposure_within_limit(self):
        self.mock_broker.positions.return_value = {"SPY": 100}
        self.mock_broker.last_price.return_value = 100.0
        # existing: 10000, new: 15000, total: 25000 < 80000
        result = self.rm.approve("AAPL", 100, 150.0)
        self.assertTrue(result)

    # ── reset_halt ─────────────────────────────────────────────────────────────
    def test_reset_halt(self):
        self.rm._halted = True
        self.rm.reset_halt()
        self.assertFalse(self.rm._halted)

    # ── Kelly fraction ─────────────────────────────────────────────────────────
    def test_kelly_no_trades_returns_default(self):
        k = self.rm.kelly_fraction()
        self.assertAlmostEqual(k, 0.01)

    def test_kelly_all_wins(self):
        for _ in range(30):
            self.rm.record_trade(100.0, 1000.0)  # $100 win on $1000 risk
        k = self.rm.kelly_fraction()
        # All wins → avg_loss=0 → falls back to TRADE_RISK_PCT
        self.assertAlmostEqual(k, 0.01)

    def test_kelly_all_losses(self):
        for _ in range(30):
            self.rm.record_trade(-500.0, 1000.0)
        k = self.rm.kelly_fraction()
        self.assertAlmostEqual(k, 0.01)  # defaults to TRADE_RISK_PCT

    def test_record_trade_trims_history(self):
        for i in range(200):
            self.rm.record_trade(50 if i % 2 == 0 else -30, 1000.0)
        self.assertLessEqual(len(self.rm._trade_log), 200)

    # ── ATR multiplier ─────────────────────────────────────────────────────────
    def test_atr_mult_low_vol(self):
        self.rm.vix = 10.0
        self.assertEqual(self.rm.get_atr_multiplier(), 1.5)

    def test_atr_mult_mid_vol(self):
        self.rm.vix = 20.0
        self.assertEqual(self.rm.get_atr_multiplier(), 2.0)

    def test_atr_mult_high_vol(self):
        self.rm.vix = 30.0
        self.assertEqual(self.rm.get_atr_multiplier(), 3.0)

    # ── Intraday peak ──────────────────────────────────────────────────────────
    def test_update_intraday_peak(self):
        self.assertIsNone(self.rm._intraday_peak)
        self.mock_broker.net_liquidation.return_value = 105_000.0
        self.rm.update_intraday_peak()
        self.assertEqual(self.rm._intraday_peak, 105_000.0)
        self.mock_broker.net_liquidation.return_value = 103_000.0
        self.rm.update_intraday_peak()
        self.assertEqual(self.rm._intraday_peak, 105_000.0)  # unchanged

    # ── Intraday drawdown halt ─────────────────────────────────────────────────
    def test_approve_intraday_drawdown(self):
        from datetime import date
        self.rm._today = date.today()
        self.rm._week_number = date.today().isocalendar()[1]
        self.rm._day_start_equity = 102_000.0
        self.rm._intraday_peak = 102_000.0
        self.mock_broker.net_liquidation.return_value = 100_000.0
        self.mock_broker.daily_pnl.return_value = 0.0
        # drawdown = (102000 - 100000) / 102000 ≈ 1.96% > 1.5%
        result = self.rm.approve("AAPL", 100, 150.0)
        self.assertFalse(result)
        self.assertTrue(self.rm._halted)


if __name__ == "__main__":
    unittest.main()
