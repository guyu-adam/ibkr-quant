"""
慢速交易 v2 — 港股 IPO 打新 + 时区套利 (ADR → 港股)。

完整实现:
  - HkIpoStrategy: 灰市溢价筛选 → 首日开盘买入 → 目标止盈/止损
  - TimezoneArbitrageStrategy: ADR 隔夜涨跌 → 港股开盘顺势套利
"""

import logging
import numpy as np
import pandas as pd
import yfinance as yf

from core.strategy_base import BaseStrategy

log = logging.getLogger(__name__)

# ── ADR → HK ticker mapping ────────────────────────────────────────────
ADR_MAP = {
    "BABA":  "9988.HK",
    "JD":    "9618.HK",
    "BIDU":  "9888.HK",
    "NTES":  "9999.HK",
    "BILI":  "9626.HK",
    "TME":   "1698.HK",
    "NIO":   "9866.HK",
    "XPEV":  "9868.HK",
    "LI":    "2015.HK",
    "TCOM":  "9961.HK",
    "ZTO":   "2057.HK",
    "BGNE":  "6160.HK",
    "HCM":   "1801.HK",
    "YMM":   "9699.HK",
    "BEKE":  "2423.HK",
}


class HkIpoStrategy(BaseStrategy):
    """
    HK IPO Pop — 灰市溢价 ≥ threshold 时首日开盘买入，目标捕捉溢价的 60%。

    Requires:
      - 港股 IPO 日历数据（外部 API 或手动录入）
      - 灰市溢价数据
    """

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.min_grey_premium = cfg.get("min_grey_premium", 0.15)
        self.stop_pct = cfg.get("stop_pct", 0.05)
        self.target_ratio = cfg.get("target_pct_of_premium", 0.60)
        self.max_risk_pct = cfg.get("max_risk_per_trade", 0.015)
        self.max_positions = cfg.get("max_concurrent_positions", 2)
        self._active_ipo: dict[str, dict] = {}

    @property
    def name(self) -> str:
        return "hk_ipo"

    def on_bar(self, data: dict) -> list:
        return []

    def on_close(self) -> None:
        self._active_ipo.clear()

    def screen_and_trade(self, broker, ipo_calendar: list[dict]) -> list[dict]:
        """
        Screen upcoming IPOs and generate trade signals.

        Args:
            broker: broker instance with market_order()
            ipo_calendar: list of dicts with keys:
                - symbol: HK ticker (e.g. "0001.HK")
                - ipo_price: IPO offer price
                - grey_premium: grey market premium as decimal (e.g. 0.20 = +20%)
                - listing_date: listing date string
                - name: company name

        Returns:
            list of trade signal dicts
        """
        signals = []

        for ipo in ipo_calendar:
            symbol = ipo.get("symbol", "")
            grey = ipo.get("grey_premium", 0)
            ipo_price = ipo.get("ipo_price", 0)

            if grey < self.min_grey_premium or ipo_price <= 0:
                continue

            if len(self._active_ipo) >= self.max_positions:
                continue

            if symbol in self._active_ipo:
                # Check exit conditions
                pos = self._active_ipo[symbol]
                current_price = broker.last_price(symbol)

                if current_price <= 0:
                    continue

                pnl_pct = (current_price - pos["entry_price"]) / pos["entry_price"]

                # Target hit
                target_price = ipo_price * (1 + grey * self.target_ratio)
                if current_price >= target_price:
                    signals.append({
                        "signal": "sell", "symbol": symbol,
                        "reason": f"IPO target: {pnl_pct:.1%} >= {grey * self.target_ratio:.1%}",
                    })
                    del self._active_ipo[symbol]

                # Stop hit
                elif current_price <= ipo_price * (1 - self.stop_pct):
                    signals.append({
                        "signal": "sell", "symbol": symbol,
                        "reason": f"IPO stop: {pnl_pct:.1%}",
                    })
                    del self._active_ipo[symbol]
            else:
                # Fresh entry
                target_price = ipo_price * (1 + grey * self.target_ratio)
                risk_per_share = ipo_price * self.stop_pct
                equity = broker.net_liquidation() or 100_000
                risk_amount = equity * self.max_risk_pct
                shares = int(risk_amount / risk_per_share) if risk_per_share > 0 else 0

                if shares <= 0:
                    continue

                signals.append({
                    "signal": "buy", "symbol": symbol, "shares": shares,
                    "reason": (f"IPO: grey_premium={grey:.0%} ipo_price={ipo_price:.2f} "
                               f"target={target_price:.2f}"),
                })
                self._active_ipo[symbol] = {
                    "entry_price": ipo_price, "grey_premium": grey,
                    "target_price": target_price,
                    "listing_date": ipo.get("listing_date", ""),
                }

        return signals


class TimezoneArbitrageStrategy(BaseStrategy):
    """
    ADR → HK 时区套利 — 利用美股 ADR 隔夜涨跌在港股开盘时套利。

    Flow:
      1. 美股收盘后获取 ADR 涨跌幅
      2. 若 ADR 涨跌幅 ≥ threshold，在港股开盘买入/卖出对应正股
      3. 持仓到港股收盘或目标/止损触发
    """

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.adr_threshold = cfg.get("adr_threshold", 0.015)
        self.position_risk_pct = cfg.get("position_risk_pct", 0.01)
        self.stop_pct = cfg.get("stop_pct", 0.02)
        self.target_ratio = cfg.get("target_ratio", 2.0)
        self.max_positions = cfg.get("max_positions", 3)
        self.allow_short = cfg.get("allow_short", False)
        self.hkd_usd_rate = cfg.get("hkd_usd_rate", 7.8)
        self._active: dict[str, dict] = {}
        self._adr_map = ADR_MAP

    @property
    def name(self) -> str:
        return "timezone_arb"

    def on_bar(self, data: dict) -> list:
        return []

    def on_close(self) -> None:
        self._active.clear()

    def get_adr_moves(self) -> dict[str, dict]:
        """
        Fetch ADR overnight moves from yfinance.

        Returns:
            {adr_ticker: {move: float, hk_ticker: str, adr_close: float, prev_close: float}}
        """
        results = {}
        for adr, hk in self._adr_map.items():
            try:
                ticker = yf.Ticker(adr)
                hist = ticker.history(period="5d")
                if len(hist) < 2:
                    continue
                close_latest = float(hist["Close"].iloc[-1])
                close_prev = float(hist["Close"].iloc[-2])
                move = (close_latest - close_prev) / close_prev if close_prev > 0 else 0
                if abs(move) >= self.adr_threshold:
                    results[adr] = {
                        "move": move, "hk_ticker": hk,
                        "adr_close": close_latest, "prev_close": close_prev,
                    }
            except Exception as e:
                log.debug(f"ADR fetch {adr}: {e}")
        return results

    def screen_and_trade(self, broker) -> list[dict]:
        """
        Screen ADR moves and generate HK trade signals.

        Args:
            broker: broker instance with market_order() and last_price()

        Returns:
            list of trade signal dicts
        """
        signals = []

        # Check exits first
        for key in list(self._active.keys()):
            pos = self._active[key]
            hk_ticker = pos["hk_ticker"]
            price = broker.last_price(hk_ticker)
            if price <= 0:
                continue

            pnl_pct = (price - pos["entry_price"]) / pos["entry_price"]
            if pos["direction"] == "short":
                pnl_pct = -pnl_pct

            target_pct = abs(pos["adr_move"]) * self.target_ratio

            if pnl_pct >= target_pct:
                action = "sell" if pos["direction"] == "long" else "buy"
                signals.append({
                    "signal": action, "symbol": hk_ticker,
                    "reason": f"TZ-ARB target: {pnl_pct:.1%} >= {target_pct:.1%}",
                })
                del self._active[key]
            elif pnl_pct <= -self.stop_pct:
                action = "sell" if pos["direction"] == "long" else "buy"
                signals.append({
                    "signal": action, "symbol": hk_ticker,
                    "reason": f"TZ-ARB stop: {pnl_pct:.1%}",
                })
                del self._active[key]

        # Screen new entries
        if len(self._active) >= self.max_positions:
            return signals

        adr_moves = self.get_adr_moves()
        equity = broker.net_liquidation() or 100_000

        for adr, info in adr_moves.items():
            if len(self._active) >= self.max_positions:
                break

            hk_ticker = info["hk_ticker"]
            if hk_ticker in {p["hk_ticker"] for p in self._active.values()}:
                continue

            move = info["move"]
            direction = "long" if move > 0 else "short"

            if direction == "short" and not self.allow_short:
                continue

            hk_price = broker.last_price(hk_ticker)
            if hk_price <= 0:
                try:
                    ticker = yf.Ticker(hk_ticker)
                    info_hk = ticker.fast_info
                    hk_price = info_hk.last_price or info_hk.previous_close or 0
                except Exception:
                    continue

            if hk_price <= 0:
                continue

            risk_amount = equity * self.position_risk_pct
            stop_dist = hk_price * self.stop_pct
            shares = int(risk_amount / stop_dist) if stop_dist > 0 else 0
            if shares <= 0:
                continue

            entry_signal = "buy" if direction == "long" else "sell"
            signals.append({
                "signal": entry_signal, "symbol": hk_ticker,
                "shares": shares,
                "reason": (f"TZ-ARB: {adr} {move:+.1%} → {hk_ticker} "
                           f"direction={direction}"),
            })

            self._active[f"{adr}_{hk_ticker}"] = {
                "adr": adr, "hk_ticker": hk_ticker,
                "adr_move": move, "direction": direction,
                "entry_price": hk_price,
            }

        return signals
