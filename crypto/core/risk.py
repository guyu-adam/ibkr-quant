"""
Crypto Risk Manager — position sizing, order approval, daily loss halt.
Adapted from core/risk.py for perpetual swap contracts.
"""

import logging

from crypto.config.settings import (
    ACCOUNT_EQUITY, MAX_POSITION_PCT, MAX_TOTAL_EXPOSURE,
    MAX_DAILY_LOSS_PCT, TRADE_RISK_PCT, STOP_LOSS_PCT,
    MAX_OPEN_POSITIONS, MAX_LEVERAGE, CT_VAL,
)

log = logging.getLogger(__name__)


class CryptoRiskManager:
    def __init__(self, broker):
        self.broker = broker
        self._halted = False
        self._start_equity = None

    # ── Position sizing ─────────────────────────────────────────────────────
    def position_size(self, instId: str, price: float) -> int:
        equity = self.broker.get_usdt_equity() or ACCOUNT_EQUITY
        if equity <= 0:
            return 0

        # Max contracts based on position % of equity
        max_notional = equity * MAX_POSITION_PCT
        max_contracts = self.broker.contracts_from_usdt(instId, max_notional, price)

        # Risk-based contracts (1% equity risk / stop distance)
        stop_dist_pct = STOP_LOSS_PCT
        if stop_dist_pct > 0:
            risk_contracts = self.broker.contracts_from_usdt(
                instId, equity * TRADE_RISK_PCT / stop_dist_pct, price)
        else:
            risk_contracts = max_contracts

        result = min(max_contracts, max(risk_contracts, 1)) if max_contracts > 0 else 0
        if result == 0:
            log.debug(f"position_size=0 for {instId}: equity={equity:.0f} price={price:.2f}")
        return result

    # ── Order approval ──────────────────────────────────────────────────────
    def approve(self, instId: str, sz: int, price: float) -> bool:
        if self._halted:
            log.warning("Trading HALTED (daily loss limit)")
            return False

        equity = self.broker.get_usdt_equity() or ACCOUNT_EQUITY
        if equity <= 0:
            return False

        # Track starting equity
        if self._start_equity is None:
            self._start_equity = equity

        # Daily loss check
        pnl = self.broker.daily_pnl()
        if pnl < -self._start_equity * MAX_DAILY_LOSS_PCT:
            self._halted = True
            log.warning(f"Daily loss limit hit: PnL={pnl:.2f} "
                        f"< -{self._start_equity * MAX_DAILY_LOSS_PCT:.2f} → HALTED")
            return False

        # Total exposure check
        positions = self.broker.get_positions()
        current_exposure = 0.0
        for sym, pos in positions.items():
            qty = abs(float(pos.get("pos", 0)))
            ctVal = CT_VAL.get(sym, 0.01)
            pos_price = float(pos.get("avgPx", 0)) or price
            current_exposure += qty * pos_price * ctVal

        ctVal = CT_VAL.get(instId, 0.01)
        new_exposure = current_exposure + sz * price * ctVal
        if new_exposure > equity * MAX_TOTAL_EXPOSURE:
            log.warning(f"Total exposure limit: {new_exposure:.0f} "
                        f"> {equity * MAX_TOTAL_EXPOSURE:.0f}")
            return False

        # Effective leverage check
        if equity > 0 and new_exposure / equity > MAX_LEVERAGE:
            log.warning(f"Leverage limit: {new_exposure / equity:.1f}x > {MAX_LEVERAGE}x")
            return False

        # Max open positions
        open_count = sum(1 for p in positions.values() if float(p.get("pos", 0)) != 0)
        if open_count >= MAX_OPEN_POSITIONS:
            log.warning(f"Max open positions: {open_count} >= {MAX_OPEN_POSITIONS}")
            return False

        return True

    def reset_halt(self):
        self._halted = False
        self._start_equity = None
        log.info("Risk halt reset")
