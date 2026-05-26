"""Parameterized BrokerInterface contract tests — verify all adapters."""
import unittest
from core.broker_interface import BrokerInterface


class TestBrokerInterfaceContract(unittest.TestCase):
    """Verify BrokerInterface ABC enforces the contract."""

    def test_cannot_instantiate_abstract(self):
        with self.assertRaises(TypeError):
            BrokerInterface()

    def test_minimal_subclass_valid(self):
        class B(BrokerInterface):
            def connect(self): pass
            def disconnect(self): pass
            def net_liquidation(self) -> float: return 0.0
            def daily_pnl(self) -> float: return 0.0
            def positions(self) -> dict[str, float]: return {}
            def last_price(self, symbol: str) -> float: return 0.0
            def market_order(self, symbol: str, shares: int, action: str): pass

        b = B()
        self.assertIsInstance(b, BrokerInterface)

    def test_missing_method_fails(self):
        class B(BrokerInterface):
            def connect(self): pass
            def disconnect(self): pass
            def net_liquidation(self) -> float: return 0.0
            def daily_pnl(self) -> float: return 0.0
            # missing positions, last_price, market_order
        with self.assertRaises(TypeError):
            B()


class TestAllBrokersImplementInterface(unittest.TestCase):
    """Verify every concrete broker satisfies BrokerInterface."""

    def _check_broker(self, cls):
        self.assertTrue(issubclass(cls, BrokerInterface),
                        f"{cls.__name__} must inherit BrokerInterface")
        required = ["connect", "disconnect", "net_liquidation", "daily_pnl",
                    "positions", "last_price", "market_order"]
        for method in required:
            self.assertTrue(hasattr(cls, method),
                            f"{cls.__name__} missing {method}")

    def test_ibkr_broker(self):
        from interfaces.ibkr import IBKRBroker
        self._check_broker(IBKRBroker)

    def test_okx_broker(self):
        from interfaces.okx import OKXBroker
        self._check_broker(OKXBroker)

    def test_binance_broker(self):
        from interfaces.binance import BinanceBroker
        self._check_broker(BinanceBroker)

    def test_schwab_broker(self):
        from interfaces.schwab import SchwabBroker
        self._check_broker(SchwabBroker)

    def test_ths_broker(self):
        from interfaces.ths import THSBroker
        self._check_broker(THSBroker)

    def test_simulation_broker(self):
        from paper_trading.engine import SimulationBroker
        self._check_broker(SimulationBroker)

    def test_backtest_broker(self):
        from core.backtest import BacktestBroker
        self._check_broker(BacktestBroker)


if __name__ == "__main__":
    unittest.main()
