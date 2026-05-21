"""
Timezone Arbitrage Strategy
────────────────────────────
Logic:
  US session (4pm ET close) → observe ADR move vs previous HK close
  Overnight signal → trade corresponding HK stock at HK market open (9:30 HKT)

  Also runs intra-session:
    HK afternoon close → predict US ADR opening gap (reverse direction)

ADR pairs tracked:
  BABA  ↔ 9988.HK    Alibaba
  JD    ↔ 9618.HK    JD.com
  PDD   ↔ 9999.HK    PDD Holdings
  NTES  ↔ 9999.HK    — skipped if 9999 conflicts
  BIDU  ↔ 9888.HK    Baidu
  NIO   ↔ 9866.HK    NIO
  XPEV  ↔ 9868.HK    XPeng
  LI    ↔ 2015.HK    Li Auto

Signal: if ADR_pct_change since HK_close > threshold → go long HK at open
         if ADR_pct_change < -threshold → go short (if margin enabled)
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import yfinance as yf
import pandas as pd

log = logging.getLogger(__name__)

ADR_PAIRS = {
    "BABA":  "9988.HK",
    "JD":    "9618.HK",
    "PDD":   "9999.HK",
    "BIDU":  "9888.HK",
    "NIO":   "9866.HK",
    "XPEV":  "9868.HK",
    "LI":    "2015.HK",
}

# ── data helpers ──────────────────────────────────────────────────────────────

def _get_close(ticker: str, days_back: int = 5) -> Optional[pd.Series]:
    try:
        df = yf.download(ticker, period=f"{days_back}d", interval="1d",
                         progress=False, auto_adjust=True)
        if df.empty:
            return None
        return df["Close"]
    except Exception as e:
        log.debug(f"yfinance {ticker}: {e}")
        return None


def compute_signals(threshold: float = 0.015) -> list[dict]:
    """
    Returns list of signals based on overnight ADR moves.
    threshold: minimum ADR move (1.5% default) to trigger a signal.

    Returns: [{"hk_code": "9988", "adr": "BABA", "signal": +1/-1,
               "adr_move": 0.032, "description": "..."}]
    """
    signals = []
    for adr, hk_yahoo in ADR_PAIRS.items():
        try:
            adr_s = _get_close(adr, days_back=5)
            hk_s  = _get_close(hk_yahoo, days_back=5)
            if adr_s is None or hk_s is None or len(adr_s) < 2 or len(hk_s) < 2:
                continue

            # ADR move: yesterday's close vs day before (US session move)
            adr_today_close = float(adr_s.iloc[-1])
            adr_prev_close  = float(adr_s.iloc[-2])
            adr_move = (adr_today_close - adr_prev_close) / adr_prev_close

            # HK last close (before this US session started)
            hk_last_close = float(hk_s.iloc[-1])

            if abs(adr_move) < threshold:
                continue

            direction = 1 if adr_move > 0 else -1
            hk_code   = hk_yahoo.replace(".HK", "")

            signals.append({
                "hk_code":   hk_code,
                "hk_ticker": hk_yahoo,
                "adr":       adr,
                "signal":    direction,
                "adr_move":  adr_move,
                "hk_ref":    hk_last_close,
                "description": (
                    f"{adr} moved {adr_move:+.1%} overnight → "
                    f"{'LONG' if direction > 0 else 'SHORT'} {hk_code}.HK"
                ),
            })
            log.info(f"[TZ_ARB] {signals[-1]['description']}")

        except Exception as e:
            log.warning(f"[TZ_ARB] {adr}/{hk_yahoo} error: {e}")

    return signals


# ── IBKR execution ────────────────────────────────────────────────────────────

def _hk_stock(broker, code: str):
    from ib_insync import Stock
    c = Stock(code, "SEHK", "HKD")
    broker.ib.qualifyContracts(c)
    return c


class TZArbStrategy:
    """
    Runs at HK market open after overnight ADR signal computation.
    Holds for intraday or until stop/target hit; closes at HK 3:30 pm.
    """

    DEFAULT_CFG = {
        "adr_threshold":          0.015,   # min 1.5% ADR move to trade
        "position_risk_pct":      0.01,    # 1% equity risk per position
        "stop_pct":               0.02,    # 2% stop loss from entry
        "target_ratio":           2.0,     # risk:reward = 1:2
        "max_positions":          3,
        "allow_short":            False,   # requires margin account
        "hkd_usd_rate":           7.8,
    }

    def __init__(self, broker, risk_mgr, cfg: dict = None):
        self.broker   = broker
        self.risk_mgr = risk_mgr
        self.cfg      = {**self.DEFAULT_CFG, **(cfg or {})}
        self._active  = {}   # code → {"side": +1/-1, "entry": price, "stop": price}

    def compute(self) -> list[dict]:
        """Call this BEFORE HK open (e.g. 8:50 HKT) to get today's signals."""
        return compute_signals(threshold=self.cfg["adr_threshold"])

    def execute(self, signals: list[dict]):
        """Place orders at HK market open based on precomputed signals."""
        for sig in signals:
            if len(self._active) >= self.cfg["max_positions"]:
                break

            code    = sig["hk_code"]
            side    = sig["signal"]

            if side == -1 and not self.cfg["allow_short"]:
                log.info(f"[TZ_ARB] Short not allowed, skip {code}")
                continue

            if code in self._active:
                continue

            try:
                ref_px   = sig["hk_ref"]
                stop_px  = ref_px * (1 - side * self.cfg["stop_pct"])
                tgt_px   = ref_px * (1 + side * self.cfg["stop_pct"] * self.cfg["target_ratio"])

                equity = self.broker.net_liquidation()
                risk_hkd = equity * self.cfg["position_risk_pct"] * self.cfg["hkd_usd_rate"]
                shares   = int(risk_hkd / (ref_px * self.cfg["stop_pct"]) / 100) * 100

                if shares <= 0 or not self.risk_mgr.approve(code, shares, ref_px):
                    continue

                action = "BUY" if side > 0 else "SELL"
                contract = _hk_stock(self.broker, code)
                trade = self.broker.ib.placeOrder(
                    contract,
                    self.broker.ib.order("MKT", action, shares)
                )
                self._active[code] = {"side": side, "entry": ref_px,
                                      "stop": stop_px, "target": tgt_px}
                log.info(f"[TZ_ARB] {action} {shares} {code}  "
                         f"entry≈{ref_px:.2f}  stop={stop_px:.2f}  tgt={tgt_px:.2f}")
            except Exception as e:
                log.error(f"[TZ_ARB] execute {code}: {e}")

    def check_exits(self):
        """Poll prices; trigger stop/target if hit."""
        for code, pos in list(self._active.items()):
            try:
                price = self.broker.last_price(code)
                if price <= 0:
                    continue
                hit = False
                if pos["side"] > 0 and (price <= pos["stop"] or price >= pos["target"]):
                    hit = True
                elif pos["side"] < 0 and (price >= pos["stop"] or price <= pos["target"]):
                    hit = True
                if hit:
                    qty = abs(self.broker.positions().get(code, 0))
                    if qty > 0:
                        action = "SELL" if pos["side"] > 0 else "BUY"
                        self.broker.market_order(code, qty, action)
                        log.info(f"[TZ_ARB] Exit {code}  price={price:.2f}  "
                                 f"side={'+' if pos['side']>0 else '-'}")
                    del self._active[code]
            except Exception as e:
                log.debug(f"[TZ_ARB] check_exits {code}: {e}")

    def close_all(self):
        """EOD force-close all tz_arb positions."""
        for code in list(self._active):
            try:
                pos = self.broker.positions()
                qty = abs(pos.get(code, 0))
                if qty > 0:
                    action = "SELL" if self._active[code]["side"] > 0 else "BUY"
                    self.broker.market_order(code, qty, action)
                    log.info(f"[TZ_ARB] EOD close {code}")
            except Exception as e:
                log.error(f"[TZ_ARB] close_all {code}: {e}")
        self._active.clear()
