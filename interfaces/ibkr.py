"""
IBKR — Interactive Brokers 适配器。

Usage:
    from interfaces.ibkr import IBKRBroker
    broker = IBKRBroker()
    broker.connect()
    broker.market_order("AAPL", 100, "BUY")
"""

import logging
from config.settings import IBKR_HOST, IBKR_PORT, IBKR_CLIENT

log = logging.getLogger(__name__)


class IBKRBroker:
    """ib_insync wrapper for Interactive Brokers."""

    def __init__(self, host=IBKR_HOST, port=IBKR_PORT, client_id=IBKR_CLIENT):
        self.host = host
        self.port = port
        self.client_id = client_id
        self._ib = None
        self._connected = False

    def connect(self):
        try:
            from ib_insync import IB
            self._ib = IB()
            self._ib.connect(self.host, self.port, clientId=self.client_id)
            self._connected = True
            log.info(f"IBKR connected {self.host}:{self.port}")
        except Exception as e:
            log.error(f"IBKR connect failed: {e}")
            raise

    def disconnect(self):
        if self._ib and self._connected:
            self._ib.disconnect()
            self._connected = False
            log.info("IBKR disconnected")

    def account(self):
        return self._ib.managedAccounts()[0] if self._ib else ""

    def net_liquidation(self) -> float:
        try:
            acct = self._ib.accountSummary()
            for a in acct:
                if a.tag == "NetLiquidation":
                    return float(a.value)
        except Exception:
            pass
        return None

    def daily_pnl(self) -> float:
        try:
            acct = self._ib.accountSummary()
            for a in acct:
                if a.tag == "RealizedPnL":
                    return float(a.value)
        except Exception:
            pass
        return 0.0

    def positions(self) -> dict:
        try:
            return {p.contract.symbol: p.position for p in self._ib.positions()}
        except Exception:
            return {}

    def last_price(self, symbol: str) -> float:
        try:
            from ib_insync import Stock
            contract = Stock(symbol, "SMART", "USD")
            self._ib.qualifyContracts(contract)
            ticker = self._ib.reqMktData(contract)
            self._ib.sleep(1)
            return float(ticker.last or 0)
        except Exception:
            return 0.0

    def market_order(self, symbol: str, shares: int, action: str):
        try:
            from ib_insync import Stock, MarketOrder
            contract = Stock(symbol, "SMART", "USD")
            self._ib.qualifyContracts(contract)
            order = MarketOrder(action.upper(), abs(shares))
            trade = self._ib.placeOrder(contract, order)
            log.info(f"IBKR {action} {shares} {symbol}")
            return trade
        except Exception as e:
            log.error(f"IBKR order failed: {e}")
            raise
