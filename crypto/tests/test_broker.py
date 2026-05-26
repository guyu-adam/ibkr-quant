"""Tests for OKXBroker and MockBroker."""
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock

# Path setup
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestMockBroker:
    @pytest.fixture
    def broker(self):
        from crypto.core.mock_broker import MockBroker
        b = MockBroker()
        b.connect()
        return b

    def test_initial_equity(self, broker):
        assert broker.get_usdt_equity() == 1000.0

    def test_get_ticker_has_expected_keys(self, broker):
        t = broker.get_ticker("BTC-USDT-SWAP")
        assert t is not None
        assert "last" in t
        assert float(t["last"]) > 0

    def test_get_candlesticks_returns_dataframe(self, broker):
        df = broker.get_candlesticks("BTC-USDT-SWAP", bar="5m", limit=50)
        assert isinstance(df, pd.DataFrame)
        assert len(df) >= 50
        assert "close" in df.columns
        assert "open" in df.columns

    def test_contracts_from_usdt_btc(self, broker):
        # 100 USDT at 68000 BTC price with ctVal=0.01 → > 0 contracts
        sz = broker.contracts_from_usdt("BTC-USDT-SWAP", 100, 68000)
        assert sz > 0
        # 1 USDT at 68000 is too small for 1 min contract
        sz_small = broker.contracts_from_usdt("BTC-USDT-SWAP", 1, 68000)
        assert sz_small >= 1  # minSz is 1

    def test_market_buy_creates_position(self, broker):
        price = broker.last_price("ETH-USDT-SWAP")
        sz = broker.contracts_from_usdt("ETH-USDT-SWAP", 500, price)
        assert sz > 0
        trade = broker.market_buy("ETH-USDT-SWAP", str(sz))
        assert trade is not None
        positions = broker.get_positions()
        assert "ETH-USDT-SWAP" in positions

    def test_market_sell_closes_position(self, broker):
        price = broker.last_price("SOL-USDT-SWAP")
        sz = broker.contracts_from_usdt("SOL-USDT-SWAP", 100, price)
        broker.market_buy("SOL-USDT-SWAP", str(sz))
        pos_before = broker.get_positions()
        assert "SOL-USDT-SWAP" in pos_before

        broker.market_sell("SOL-USDT-SWAP", str(sz))
        pos_after = broker.get_positions()
        assert "SOL-USDT-SWAP" not in pos_after

    def test_daily_pnl_updates_after_trades(self, broker):
        assert broker.daily_pnl() == 0.0  # no positions initially

    def test_multiple_tickers(self, broker):
        from crypto.config.settings import SYMBOLS
        for sym in SYMBOLS:
            t = broker.get_ticker(sym)
            assert t is not None
            assert float(t["last"]) > 0


class TestOKXBrokerNoKeys:
    def test_broker_initializes_readonly_without_keys(self):
        from crypto.core.okx_broker import OKXBroker
        broker = OKXBroker(api_key=None, secret_key=None, passphrase=None)
        broker.connect()
        assert not broker._has_keys
        # get_ticker returns None without API keys
        t = broker.get_ticker("BTC-USDT-SWAP")
        assert t is None

    def test_contracts_uses_fallback_ctval(self):
        from crypto.core.okx_broker import OKXBroker
        broker = OKXBroker(api_key=None, secret_key=None, passphrase=None)
        sz = broker.contracts_from_usdt("BTC-USDT-SWAP", 680, 68000)
        assert sz > 0  # should use fallback ctVal=0.01
