"""
风险控制 — 仓位规模计算、订单审批、日亏损熔断。
"""

import logging
from config.settings import (
    MAX_POSITION_PCT, MAX_TOTAL_EXPOSURE, MAX_DAILY_LOSS_PCT,
    STOP_LOSS_ATR_MULT, TRADE_RISK_PCT, ACCOUNT_EQUITY,
)

log = logging.getLogger(__name__)


class RiskManager:
    def __init__(self, broker):
        self.broker = broker
        self._halted = False

    def position_size(self, price: float, atr: float) -> int:
        """Volatility-adjusted position sizing."""
        equity = self.broker.net_liquidation()
        if equity is None or equity <= 0:
            equity = ACCOUNT_EQUITY
            log.warning(f"NLV unavailable, using fallback equity={equity}")
        if equity <= 0:
            return 0
        risk_amt = equity * TRADE_RISK_PCT
        stop_dist = atr * STOP_LOSS_ATR_MULT
        if stop_dist <= 0:
            return 0
        shares = int(risk_amt / stop_dist)
        max_shares = int(equity * MAX_POSITION_PCT / price)
        return min(shares, max_shares)

    def approve(self, symbol: str, shares: int, price: float) -> bool:
        """Return True if trade passes all risk checks."""
        if self._halted:
            log.warning("Trading HALTED (daily loss limit)")
            return False

        equity = self.broker.net_liquidation()
        if equity is None or equity <= 0:
            equity = ACCOUNT_EQUITY
        if equity <= 0:
            return False

        pnl = self.broker.daily_pnl()
        if pnl < -equity * MAX_DAILY_LOSS_PCT:
            self._halted = True
            log.warning("Daily loss limit hit — trading halted")
            return False

        positions = self.broker.positions()
        current_exposure = sum(
            abs(qty) * self.broker.last_price(sym)
            for sym, qty in positions.items()
        )
        new_exposure = current_exposure + shares * price
        if new_exposure > equity * MAX_TOTAL_EXPOSURE:
            log.warning(f"Total exposure limit: {new_exposure:.0f} > {equity * MAX_TOTAL_EXPOSURE:.0f}")
            return False

        return True

    def reset_halt(self):
        self._halted = False
