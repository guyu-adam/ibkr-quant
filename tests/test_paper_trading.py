"""
Unit tests for paper_trading engine and strategy.
"""
import unittest
from unittest.mock import patch, MagicMock
from paper_trading.engine import PaperTradingEngine, SYMBOLS, SYMBOL_NAMES


class TestPaperTradingEngine(unittest.TestCase):
    def setUp(self):
        self.engine = PaperTradingEngine(initial_cash=50_000.0)
        self.engine.running = True

    # ── initialization ────────────────────────────────────────────────────────
    def test_initial_cash_set(self):
        self.assertEqual(self.engine.cash, 50_000.0)

    def test_total_value_equal_cash_initially(self):
        self.assertEqual(self.engine.total_value(), 50_000.0)

    def test_initial_pnl_zero(self):
        self.assertEqual(self.engine.total_pnl(), 0.0)

    def test_initial_return_zero(self):
        self.assertEqual(self.engine.daily_return_pct(), 0.0)

    def test_no_positions_initially(self):
        self.assertEqual(len(self.engine.positions), 0)

    # ── quote update ──────────────────────────────────────────────────────────
    @patch("paper_trading.engine._requests.get")
    def test_update_quotes_sets_prices(self, mock_get):
        """Mock Tencent API response to verify price parsing."""
        mock_resp = MagicMock()
        # Tencent API format: v_sh600519="1~Kweichow~600519~1750.00~..."
        mock_resp.text = (
            'v_sh600519="1~Kweichow Moutai~600519~1750.00~..."\n'
            'v_sz000001="1~Ping An Bank~000001~12.50~..."\n'
        )
        mock_resp.encoding = "gbk"
        mock_get.return_value = mock_resp

        self.engine.update_quotes()
        self.assertIsNotNone(self.engine.quote_time)
        self.assertIn("600519", self.engine.latest_prices)

    @patch("paper_trading.engine._requests.get")
    def test_update_quotes_handles_empty(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = ""
        mock_resp.encoding = "gbk"
        mock_get.return_value = mock_resp

        self.engine.update_quotes()  # should not raise

    # ── buy / sell ────────────────────────────────────────────────────────────
    def test_buy_without_price(self):
        """Buy should be skipped when latest price is unavailable."""
        result = self.engine.buy("600519", 5000.0)
        self.assertIsNone(result)

    def test_buy_updates_cash_and_positions(self):
        """Buy with sufficient cash → updates positions and cash."""
        self.engine.latest_prices["600519"] = 100.0
        self.engine.cash = 50_000.0
        # 100/share × 100 = 10,000 per lot, 50k buys 5 lots max
        amount = 30_000  # enough for 3 lots
        result = self.engine.buy("600519", amount)
        self.assertIsNotNone(result)
        self.assertEqual(result["action"], "BUY")
        self.assertIn("600519", self.engine.positions)
        self.assertLess(self.engine.cash, 50_000.0)

    def test_buy_insufficient_cash_clamped(self):
        self.engine.latest_prices["600519"] = 1700.0
        self.engine.cash = 100.0
        result = self.engine.buy("600519", 5000.0)
        self.assertIsNone(result)  # 100 < 1700*100

    def test_sell_empty_position(self):
        result = self.engine.sell("600519")
        self.assertIsNone(result)

    def test_sell_closes_position(self):
        self.engine.latest_prices["600519"] = 1700.0
        self.engine.positions["600519"] = {"shares": 200, "avg_cost": 1700.0, "stop_loss": 1615.0}
        self.engine.cash = 50_000.0
        result = self.engine.sell("600519")
        self.assertIsNotNone(result)
        self.assertEqual(result["action"], "SELL")
        self.assertNotIn("600519", self.engine.positions)

    # ── snapshot ──────────────────────────────────────────────────────────────
    def test_snapshot_keys(self):
        snap = self.engine.snapshot()
        for key in ["cash", "total_value", "pnl", "pnl_pct", "positions", "quote_time", "trade_count"]:
            self.assertIn(key, snap)

    # ── edge cases ────────────────────────────────────────────────────────────
    def test_zero_initial_cash(self):
        engine = PaperTradingEngine(initial_cash=0.0)
        self.assertEqual(engine.daily_return_pct(), 0.0)

    def test_unrealized_pnl_unknown_symbol(self):
        self.assertEqual(self.engine.unrealized_pnl("UNKNOWN"), 0.0)

    def test_buy_zero_price_skipped(self):
        self.engine.latest_prices["600519"] = 0.0
        result = self.engine.buy("600519", 5000.0)
        self.assertIsNone(result)


class TestSymbolMapping(unittest.TestCase):
    def test_sh_sz_prefixes(self):
        """6xxxxx → .SS (Shanghai), others → .SZ (Shenzhen)."""
        def _to_yf(s): return f'{s}.SS' if s.startswith('6') else f'{s}.SZ'
        self.assertTrue(_to_yf("600519").endswith(".SS"))
        self.assertTrue(_to_yf("000001").endswith(".SZ"))
        self.assertTrue(_to_yf("300750").endswith(".SZ"))


class TestSymbolNames(unittest.TestCase):
    def test_all_symbols_have_names(self):
        for sym in SYMBOLS:
            self.assertIn(sym, SYMBOL_NAMES)
            self.assertIsInstance(SYMBOL_NAMES[sym], str)
            self.assertTrue(len(SYMBOL_NAMES[sym]) > 0)


class TestStrategyIntegration(unittest.TestCase):
    """Integration: strategy.evaluate() with mocked data."""

    @patch("core.data_feed.CachedFeed.fetch_history")
    def test_evaluate_hold_when_no_data(self, mock_fetch):
        mock_fetch.return_value = None
        from paper_trading.pt_strategy import evaluate
        engine = PaperTradingEngine(initial_cash=10_000.0)
        result = evaluate(engine, "000001")
        self.assertEqual(result, "hold")

    @patch("core.data_feed.CachedFeed.fetch_history")
    def test_evaluate_returns_string(self, mock_fetch):
        import pandas as pd
        import numpy as np
        n = 60
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        close = np.linspace(100, 80, n)  # downtrend
        df = pd.DataFrame({
            'open': close - 0.5, 'high': close + 1,
            'low': close - 1, 'close': close,
            'volume': np.random.randint(10000, 100000, n),
        }, index=dates)
        mock_fetch.return_value = df
        from paper_trading.pt_strategy import evaluate
        engine = PaperTradingEngine(initial_cash=10_000.0)
        result = evaluate(engine, "000001")
        self.assertIn(result, ["buy", "sell", "hold"])


if __name__ == "__main__":
    unittest.main()
