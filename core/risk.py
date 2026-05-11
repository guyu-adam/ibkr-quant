"""
风险控制层
每次下单前调用 RiskManager.approve()，返回 False 则拒绝
"""

import logging
from config.settings import (
    MAX_POSITION_PCT, MAX_TOTAL_EXPOSURE, MAX_DAILY_LOSS_PCT, STOP_LOSS_ATR_MULT
)

log = logging.getLogger(__name__)


class RiskManager:
    def __init__(self, broker):
        self.broker = broker
        self._halted = False   # 触发日亏损上限后暂停交易

    # ── 仓位规模计算 ──────────────────────────────────────────────────────────
    def position_size(self, price: float, atr: float) -> int:
        """
        波动率调整仓位（Volatility-adjusted sizing）
        每笔风险 = 净值 × 1%，止损距离 = ATR × 倍数
        返回股数（整数）
        """
        equity   = self.broker.net_liquidation()
        risk_amt = equity * 0.01                        # 每笔最多亏净值 1%
        stop_dist = atr * STOP_LOSS_ATR_MULT
        if stop_dist <= 0:
            return 0
        shares = int(risk_amt / stop_dist)
        # 同时不超过单票最大仓位
        max_shares = int(equity * MAX_POSITION_PCT / price)
        return min(shares, max_shares)

    # ── 订单审批 ──────────────────────────────────────────────────────────────
    def approve(self, symbol: str, shares: int, price: float) -> bool:
        if self._halted:
            log.warning("Trading HALTED (daily loss limit)")
            return False

        equity = self.broker.net_liquidation()

        # 日亏损检查
        if self.broker.daily_pnl() < -equity * MAX_DAILY_LOSS_PCT:
            self._halted = True
            log.warning(f"Daily loss limit hit → trading halted")
            return False

        # 总敞口检查
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
        """新交易日开始时调用"""
        self._halted = False
