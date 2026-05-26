"""
风险控制 v3 — 分层熔断 + 分数凯利 + 自适应止损。

Kill switch layers: intraday(-1.5%) → daily(-2%) → weekly(-5%)
Kelly sizing: f* = (bp - q) / b, applied as half-Kelly with 2% cap
Adaptive ATR: stop multiplier varies with VIX regime
"""

import logging
import numpy as np
from datetime import date
from config.settings import (
    MAX_POSITION_PCT, MAX_TOTAL_EXPOSURE, MAX_DAILY_LOSS_PCT,
    MAX_WEEKLY_LOSS_PCT, MAX_INTRADAY_LOSS_PCT,
    STOP_LOSS_ATR_MULT, TRADE_RISK_PCT, ACCOUNT_EQUITY,
    KELLY_FRACTION, KELLY_MAX_PCT, KELLY_ROLLING_TRADES, KELLY_MIN_TRADES,
    ATR_MULT_LOW_VOL, ATR_MULT_MID_VOL, ATR_MULT_HIGH_VOL,
    VIX_LOW_THRESHOLD, VIX_HIGH_THRESHOLD,
)

log = logging.getLogger(__name__)


class RiskManager:
    def __init__(self, broker):
        self.broker = broker
        self._halted = False
        self._halt_reason = ""
        # Layered P&L tracking
        self._day_start_equity: float | None = None
        self._week_start_equity: float | None = None
        self._intraday_peak: float | None = None
        self._today = date.today()
        self._week_number = self._today.isocalendar()[1]
        # Kelly tracking
        self._trade_log: list[dict] = []  # [{win: bool, pnl_pct: float}, ...]
        # VIX
        self._vix = 20.0

    @property
    def vix(self): return self._vix

    @vix.setter
    def vix(self, val): self._vix = val

    # ── Layered Kill Switch ────────────────────────────────────────────────
    def _check_date_roll(self):
        today = date.today()
        wk = today.isocalendar()[1]
        equity = self._equity()
        if today != self._today:
            self._today = today
            self._day_start_equity = equity
            self._intraday_peak = equity
            self._halted = False
        if wk != self._week_number:
            self._week_number = wk
            self._week_start_equity = equity

    def _equity(self) -> float:
        e = self.broker.net_liquidation()
        return e if e and e > 0 else ACCOUNT_EQUITY

    def approve(self, symbol: str, shares: int, price: float) -> bool:
        """Layered risk checks: intraday → daily → weekly → exposure."""
        self._check_date_roll()
        equity = self._equity()

        if self._halted:
            log.warning(f"Trading HALTED: {self._halt_reason}")
            return False

        # Check broker-reported daily PnL
        pnl = self.broker.daily_pnl()
        if pnl < -equity * MAX_DAILY_LOSS_PCT:
            self._halted = True
            self._halt_reason = f"daily PnL {pnl:.0f}"
            log.warning(f"HALT: {self._halt_reason}")
            return False

        if self._day_start_equity and self._intraday_peak:
            intraday_dd = (self._intraday_peak - equity) / self._intraday_peak
            if intraday_dd > MAX_INTRADAY_LOSS_PCT:
                self._halted = True
                self._halt_reason = f"intraday drawdown {intraday_dd:.1%}"
                log.warning(f"HALT: {self._halt_reason}")
                return False

        if self._day_start_equity and self._day_start_equity > 0:
            daily_loss = (self._day_start_equity - equity) / self._day_start_equity
            if daily_loss > MAX_DAILY_LOSS_PCT:
                self._halted = True
                self._halt_reason = f"daily loss {daily_loss:.1%}"
                log.warning(f"HALT: {self._halt_reason}")
                return False

        if self._week_start_equity and self._week_start_equity > 0:
            weekly_loss = (self._week_start_equity - equity) / self._week_start_equity
            if weekly_loss > MAX_WEEKLY_LOSS_PCT:
                self._halted = True
                self._halt_reason = f"weekly loss {weekly_loss:.1%}"
                log.warning(f"HALT: {self._halt_reason}")
                return False

        positions = self.broker.positions()
        current_exposure = sum(
            abs(qty) * self.broker.last_price(sym)
            for sym, qty in positions.items()
        )
        if current_exposure + shares * price > equity * MAX_TOTAL_EXPOSURE:
            log.warning(f"Total exposure limit exceeded")
            return False

        return True

    def update_intraday_peak(self):
        eq = self._equity()
        if self._intraday_peak is None or eq > self._intraday_peak:
            self._intraday_peak = eq

    def reset_halt(self):
        self._halted = False
        self._halt_reason = ""

    # ── Adaptive ATR Stop ───────────────────────────────────────────────────
    def get_atr_multiplier(self) -> float:
        """ATR stop multiplier adapts to VIX regime."""
        if self._vix <= VIX_LOW_THRESHOLD:
            return ATR_MULT_LOW_VOL
        elif self._vix >= VIX_HIGH_THRESHOLD:
            return ATR_MULT_HIGH_VOL
        return ATR_MULT_MID_VOL

    # ── Kelly Position Sizing ───────────────────────────────────────────────
    def record_trade(self, pnl: float, risked: float):
        """Record trade outcome for Kelly estimation."""
        self._trade_log.append({"win": pnl > 0, "pnl_pct": pnl / (risked + 1e-8)})
        if len(self._trade_log) > KELLY_ROLLING_TRADES * 2:
            self._trade_log = self._trade_log[-KELLY_ROLLING_TRADES * 2:]

    def kelly_fraction(self) -> float:
        """Compute fractional Kelly bet size."""
        recent = self._trade_log[-KELLY_ROLLING_TRADES:]
        if len(recent) < KELLY_MIN_TRADES:
            return TRADE_RISK_PCT

        wins = [t for t in recent if t["win"]]
        losses = [t for t in recent if not t["win"]]
        if not losses or not wins:
            return TRADE_RISK_PCT

        avg_win = np.mean([t["pnl_pct"] for t in wins])
        avg_loss = abs(np.mean([t["pnl_pct"] for t in losses]))
        if avg_loss <= 0:
            return TRADE_RISK_PCT

        win_rate = len(wins) / len(recent)
        b = avg_win / avg_loss  # odds ratio
        kelly = max(0, (b * win_rate - (1 - win_rate)) / b)
        return min(kelly * KELLY_FRACTION, KELLY_MAX_PCT)

    def position_size(self, price: float, atr: float) -> int:
        """Kelly + volatility-adjusted position sizing."""
        equity = self._equity()
        atr_mult = self.get_atr_multiplier()
        stop_dist = atr * atr_mult

        if stop_dist <= 0 or price <= 0:
            return 0

        kelly_pct = self.kelly_fraction()
        risk_amt = equity * kelly_pct
        shares = int(risk_amt / stop_dist)
        max_shares = int(equity * MAX_POSITION_PCT / price)
        return max(0, min(shares, max_shares))
