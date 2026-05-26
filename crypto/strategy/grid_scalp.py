"""
Grid Scalping Strategy — Bollinger Bands + RSI mean reversion.
Designed for frequent trading on volatile crypto perpetual swaps.

Signal logic:
  BUY:  Price at/below lower BB + RSI oversold + volume confirmation
  SELL: Price at/above upper BB + RSI overbought + MACD death cross

Grid layering: when price keeps dropping, new entries at lower prices.
Each entry has independent TP (+2%) and SL (-1.5%).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from core.strategy_base import BaseStrategy
from crypto.config.settings import (
    BB_PERIOD, BB_STD, RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT,
    ATR_PERIOD, VOL_LOOKBACK, VOL_SPIKE_RATIO, GRID_LEVELS,
    GRID_SPACING_PCT, TAKE_PROFIT_PCT, STOP_LOSS_PCT, MIN_SCORE,
)

log = logging.getLogger(__name__)


@dataclass
class GridEntry:
    instId: str
    side: str          # "long" or "short"
    sz: int            # contracts
    entry_price: float
    tp_price: float
    sl_price: float
    timestamp: float


class GridScalpStrategy(BaseStrategy):
    """Bollinger Bands + RSI + Volume grid scalping."""

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.bb_period      = cfg.get("bb_period", BB_PERIOD)
        self.bb_std         = cfg.get("bb_std", BB_STD)
        self.rsi_period     = cfg.get("rsi_period", RSI_PERIOD)
        self.rsi_oversold   = cfg.get("rsi_oversold", RSI_OVERSOLD)
        self.rsi_overbought = cfg.get("rsi_overbought", RSI_OVERBOUGHT)
        self.atr_period     = cfg.get("atr_period", ATR_PERIOD)
        self.vol_lookback   = cfg.get("vol_lookback", VOL_LOOKBACK)
        self.vol_spike      = cfg.get("vol_spike_ratio", VOL_SPIKE_RATIO)
        self.grid_levels    = cfg.get("grid_levels", GRID_LEVELS)
        self.grid_spacing   = cfg.get("grid_spacing_pct", GRID_SPACING_PCT)
        self.tp_pct         = cfg.get("take_profit_pct", TAKE_PROFIT_PCT)
        self.sl_pct         = cfg.get("stop_loss_pct", STOP_LOSS_PCT)
        self.min_score      = cfg.get("min_score", MIN_SCORE)
        self._active_grid: dict[str, list[GridEntry]] = {}

    @property
    def name(self) -> str:
        return "grid_scalp"

    # ── BaseStrategy interface ──────────────────────────────────────────────
    def on_bar(self, data: dict) -> list:
        raise NotImplementedError("use evaluate() directly")

    def on_close(self) -> None:
        self._active_grid.clear()

    # ── Indicator helpers ───────────────────────────────────────────────────
    @staticmethod
    def _sma(series: pd.Series, period: int) -> pd.Series:
        return series.rolling(window=period).mean()

    @staticmethod
    def _ema(series: pd.Series, span: int) -> pd.Series:
        return series.ewm(span=span, adjust=False).mean()

    @staticmethod
    def _rsi(close: pd.Series, period: int) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_g = gain.ewm(alpha=1 / period, adjust=False).mean()
        avg_l = loss.ewm(alpha=1 / period, adjust=False).mean()
        rs = avg_g / avg_l.replace(0, np.nan)
        vals = 100.0 - 100.0 / (1.0 + rs)
        vals[avg_l == 0] = 100.0
        return vals

    @staticmethod
    def _atr(high: pd.Series, low: pd.Series, close: pd.Series,
             period: int) -> pd.Series:
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        return tr.ewm(alpha=1 / period, adjust=False).mean()

    @staticmethod
    def _bollinger(close: pd.Series, period: int, std_mult: float):
        mid = close.rolling(window=period).mean()
        std = close.rolling(window=period).std()
        upper = mid + std_mult * std
        lower = mid - std_mult * std
        return mid, upper, lower

    @staticmethod
    def _macd(close: pd.Series, fast: int = 12, slow: int = 26,
              signal: int = 9) -> pd.DataFrame:
        ema_f = close.ewm(span=fast, adjust=False).mean()
        ema_s = close.ewm(span=slow, adjust=False).mean()
        line = ema_f - ema_s
        sig = line.ewm(span=signal, adjust=False).mean()
        return pd.DataFrame({"line": line, "signal": sig, "histogram": line - sig})

    # ── Core evaluate ───────────────────────────────────────────────────────
    def evaluate(self, df: pd.DataFrame, instId: str,
                 positions: dict | None = None) -> dict:
        """
        Evaluate trading signal for a symbol.
        Returns:
            {"signal": "buy"|"sell"|"hold", "score": float, "price": float,
             "atr": float, "rsi": float, "reason": str,
             "tp_price": float, "sl_price": float}
        """
        result = {"signal": "hold", "score": 0.0, "price": 0.0,
                  "atr": 0.0, "rsi": 0.0, "reason": "",
                  "tp_price": 0.0, "sl_price": 0.0}

        if df is None or len(df) < max(self.bb_period, self.rsi_period, self.atr_period) + 5:
            result["reason"] = "insufficient data"
            return result

        close = df["close"].astype(float)
        high  = df["high"].astype(float)
        low   = df["low"].astype(float)
        vol   = df["vol"].astype(float)

        # Indicators
        rsi_vals = self._rsi(close, self.rsi_period)
        atr_vals = self._atr(high, low, close, self.atr_period)
        bb_mid, bb_upper, bb_lower = self._bollinger(close, self.bb_period, self.bb_std)
        ema20 = self._ema(close, 20)
        macd_df = self._macd(close)

        cur_close = float(close.iloc[-1])
        cur_rsi   = float(rsi_vals.iloc[-1]) if not pd.isna(rsi_vals.iloc[-1]) else 50.0
        cur_atr   = float(atr_vals.iloc[-1]) if not pd.isna(atr_vals.iloc[-1]) else cur_close * 0.01
        cur_bb_l  = float(bb_lower.iloc[-1]) if not pd.isna(bb_lower.iloc[-1]) else cur_close * 0.95
        cur_bb_u  = float(bb_upper.iloc[-1]) if not pd.isna(bb_upper.iloc[-1]) else cur_close * 1.05
        cur_bb_m  = float(bb_mid.iloc[-1]) if not pd.isna(bb_mid.iloc[-1]) else cur_close
        cur_ema   = float(ema20.iloc[-1])
        prev_ema  = float(ema20.iloc[-2]) if len(ema20) > 1 else cur_ema
        cur_macd_line = float(macd_df["line"].iloc[-1])
        cur_macd_sig  = float(macd_df["signal"].iloc[-1])
        cur_macd_hist = float(macd_df["histogram"].iloc[-1])

        # Volume spike detection
        avg_vol = float(vol.iloc[-self.vol_lookback:-1].mean()) if len(vol) > self.vol_lookback else 1.0
        vol_ratio = float(vol.iloc[-1]) / avg_vol if avg_vol > 0 else 1.0

        # BB width (normalized volatility)
        bb_width = (cur_bb_u - cur_bb_l) / cur_bb_m if cur_bb_m > 0 else 0.02

        result.update({
            "price": round(cur_close, 2),
            "rsi": round(cur_rsi, 2),
            "atr": round(cur_atr, 4),
            "bb_lower": round(cur_bb_l, 2),
            "bb_upper": round(cur_bb_u, 2),
            "vol_ratio": round(vol_ratio, 2),
        })

        pos = (positions or {}).get(instId)
        holding = pos is not None and float(pos.get("pos", 0)) > 0

        # Grid entries for this symbol
        active_entries = self._active_grid.get(instId, [])

        # ═══ SELL logic (holding a position) ════════════════════════════════
        if holding or active_entries:
            sell_score = 0.0

            # Price at or above upper BB → immediate sell
            if cur_close >= cur_bb_u:
                result["signal"] = "sell"
                result["score"] = 100.0
                result["reason"] = f"price {cur_close:.2f} >= BB_upper {cur_bb_u:.2f}"
                return result

            # RSI overbought
            if cur_rsi > self.rsi_overbought:
                sell_score += 30
            if cur_rsi > 80:
                sell_score += 20

            # MACD death cross
            if cur_macd_line < cur_macd_sig:
                sell_score += 25

            # Trend break: price dropped below EMA20
            if cur_close < cur_ema and cur_ema < prev_ema:
                sell_score += 15

            # Stop loss hit (check per entry)
            for entry in active_entries:
                if cur_close <= entry.sl_price:
                    result["signal"] = "sell"
                    result["score"] = 100.0
                    result["reason"] = f"stop loss: {cur_close:.2f} <= {entry.sl_price:.2f}"
                    return result
                if cur_close >= entry.tp_price:
                    result["signal"] = "sell"
                    result["score"] = 100.0
                    result["reason"] = f"take profit: {cur_close:.2f} >= {entry.tp_price:.2f}"
                    return result

            if sell_score > 0:
                result["signal"] = "sell"
                result["score"] = sell_score
                reason_parts = []
                if cur_rsi > self.rsi_overbought:
                    reason_parts.append(f"RSI={cur_rsi:.1f}")
                if cur_macd_line < cur_macd_sig:
                    reason_parts.append("MACD cross")
                if cur_close < cur_ema:
                    reason_parts.append("below EMA")
                result["reason"] = ", ".join(reason_parts)
                return result

            if active_entries:
                result["reason"] = f"holding {len(active_entries)} grid entries"
            return result

        # ═══ BUY scoring (no position) ══════════════════════════════════════
        buy_score = 0.0

        # Bollinger Band position
        if cur_close <= cur_bb_l:
            buy_score += 35
        elif cur_close <= cur_bb_l * 1.01:  # within 1% of lower band
            buy_score += 20
        elif cur_close < cur_bb_m:
            buy_score += 10

        # RSI oversold
        if cur_rsi < self.rsi_oversold:
            buy_score += 25
        if cur_rsi < 20:
            buy_score += 15

        # Volume spike (confirms capitulation)
        if vol_ratio > 1.5:
            buy_score += 10
        elif vol_ratio > self.vol_spike:
            buy_score += 5

        # Trend: EMA20 rising
        if cur_ema > prev_ema:
            buy_score += 10

        # MACD histogram improving
        if cur_macd_hist > 0:
            buy_score += 5
        if len(macd_df) >= 3:
            prev_hist = float(macd_df["histogram"].iloc[-2])
            prev2_hist = float(macd_df["histogram"].iloc[-3])
            if cur_macd_hist > prev_hist > prev2_hist:
                buy_score += 5

        # Extra: BB width (higher vol = more opportunity)
        if bb_width > 0.05:
            buy_score += 5

        # Check grid spacing — ensure new entry isn't too close to existing
        for entry in active_entries:
            dist = abs(cur_close - entry.entry_price) / entry.entry_price
            if dist < self.grid_spacing * 0.5:
                result["reason"] = f"too close to grid entry @ {entry.entry_price:.2f}"
                return result

        # Max grid levels
        if len(active_entries) >= self.grid_levels:
            result["reason"] = f"max grid levels ({self.grid_levels}) reached"
            return result

        result["score"] = round(buy_score, 1)

        if buy_score >= self.min_score:
            result["signal"] = "buy"
            result["tp_price"] = round(cur_close * (1 + self.tp_pct), 2)
            result["sl_price"] = round(cur_close * (1 - self.sl_pct), 2)
            result["reason"] = (
                f"RSI={cur_rsi:.1f} BB={'in_lower' if cur_close <= cur_bb_l else 'below_mid'} "
                f"vol_ratio={vol_ratio:.1f} score={buy_score:.1f}"
            )
        else:
            result["reason"] = f"score={buy_score:.1f} < {self.min_score}"

        return result

    # ── Grid management ─────────────────────────────────────────────────────
    def add_grid_entry(self, instId: str, sz: int, entry_price: float):
        entry = GridEntry(
            instId=instId, side="long", sz=sz,
            entry_price=entry_price,
            tp_price=round(entry_price * (1 + self.tp_pct), 2),
            sl_price=round(entry_price * (1 - self.sl_pct), 2),
            timestamp=pd.Timestamp.now().timestamp(),
        )
        self._active_grid.setdefault(instId, []).append(entry)
        log.info(f"[GRID] New entry {instId} sz={sz} @ {entry_price:.2f} "
                 f"TP={entry.tp_price:.2f} SL={entry.sl_price:.2f}")
        return entry

    def remove_grid_entry(self, instId: str, entry: GridEntry):
        entries = self._active_grid.get(instId, [])
        if entry in entries:
            entries.remove(entry)
            log.info(f"[GRID] Removed entry {instId} @ {entry.entry_price:.2f}")

    def get_grid_entries(self, instId: str) -> list[GridEntry]:
        return self._active_grid.get(instId, [])

    def grid_count(self, instId: str = None) -> int:
        if instId:
            return len(self._active_grid.get(instId, []))
        return sum(len(v) for v in self._active_grid.values())
