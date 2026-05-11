"""
IBKR 连接层 —— 基于 ib_insync
pip install ib_insync
"""

import logging
from ib_insync import IB, Stock, MarketOrder, LimitOrder, util
from config.settings import IBKR_HOST, IBKR_PORT, IBKR_CLIENT

log = logging.getLogger(__name__)


class IBKRBroker:
    def __init__(self):
        self.ib = IB()
        self._connected = False

    # ── 连接 / 断开 ──────────────────────────────────────────────────────────
    def connect(self):
        self.ib.connect(IBKR_HOST, IBKR_PORT, clientId=IBKR_CLIENT)
        self._connected = True
        log.info(f"Connected to IBKR  port={IBKR_PORT}  account={self.account()}")

    def disconnect(self):
        self.ib.disconnect()
        self._connected = False

    def account(self) -> str:
        return self.ib.managedAccounts()[0]

    # ── 账户信息 ─────────────────────────────────────────────────────────────
    def net_liquidation(self) -> float:
        vals = self.ib.accountValues(self.account())
        for v in vals:
            if v.tag == "NetLiquidation" and v.currency == "USD":
                return float(v.value)
        return 0.0

    def positions(self) -> dict:
        """返回 {symbol: quantity}"""
        return {
            p.contract.symbol: p.position
            for p in self.ib.positions()
        }

    def daily_pnl(self) -> float:
        pnl = self.ib.pnl()
        return sum(p.dailyPnL or 0 for p in pnl)

    # ── 合约 ─────────────────────────────────────────────────────────────────
    def get_contract(self, symbol: str):
        c = Stock(symbol, "SMART", "USD")
        self.ib.qualifyContracts(c)
        return c

    # ── 订单 ─────────────────────────────────────────────────────────────────
    def market_order(self, symbol: str, qty: int, action: str):
        """action: 'BUY' or 'SELL'"""
        contract = self.get_contract(symbol)
        order = MarketOrder(action, abs(qty))
        trade = self.ib.placeOrder(contract, order)
        log.info(f"Market {action} {abs(qty)} {symbol}  trade={trade.order.orderId}")
        return trade

    def limit_order(self, symbol: str, qty: int, action: str, price: float):
        contract = self.get_contract(symbol)
        order = LimitOrder(action, abs(qty), round(price, 2))
        trade = self.ib.placeOrder(contract, order)
        log.info(f"Limit {action} {abs(qty)} {symbol} @ {price}  orderId={trade.order.orderId}")
        return trade

    def cancel_all(self, symbol: str):
        for trade in self.ib.openTrades():
            if trade.contract.symbol == symbol:
                self.ib.cancelOrder(trade.order)

    # ── 实时行情订阅 ─────────────────────────────────────────────────────────
    def subscribe_realtime(self, symbol: str):
        contract = self.get_contract(symbol)
        self.ib.reqMktData(contract, "", False, False)
        return contract

    def last_price(self, symbol: str) -> float:
        contract = self.get_contract(symbol)
        ticker = self.ib.ticker(contract)
        return ticker.last or ticker.close or 0.0

    # ── 历史 K 线（用于指标计算）────────────────────────────────────────────
    def get_bars(self, symbol: str, duration="2 D", bar_size="5 mins"):
        contract = self.get_contract(symbol)
        bars = self.ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
        )
        return util.df(bars)   # columns: date open high low close volume
