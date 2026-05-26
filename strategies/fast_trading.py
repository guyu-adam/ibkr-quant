"""
快速交易 — 美股日内动量（RSI 均值回归 + MACD + EMA 趋势过滤）

5 分钟 K 线交易，目标标的：SPY, QQQ, NVDA, AAPL, MSFT, TSLA, AMZN 等。

Usage:
    from strategies.fast_trading import MeanReversionStrategy, PositionSizer
    strategy = MeanReversionStrategy(config)
    result = strategy.evaluate(feed, "SPY", positions)
"""

import logging
import pandas as pd
import numpy as np

from core.strategy_base import BaseStrategy
from core.data_feed import DataFeed

log = logging.getLogger(__name__)


class MeanReversionStrategy(BaseStrategy):
    """RSI 超卖反弹 + MACD 底背离确认 + 成交量验证"""

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.rsi_period      = cfg.get('rsi_period', 14)
        self.rsi_oversold    = cfg.get('rsi_oversold', 30)
        self.rsi_overbought  = cfg.get('rsi_overbought', 70)
        self.atr_period      = cfg.get('atr_period', 14)
        self.atr_stop_mult   = cfg.get('atr_stop_mult', 2.0)
        self.macd_fast       = cfg.get('macd_fast', 12)
        self.macd_slow       = cfg.get('macd_slow', 26)
        self.macd_signal     = cfg.get('macd_signal', 9)
        self.vol_lookback    = cfg.get('vol_lookback', 20)
        self.vol_spike_ratio = cfg.get('vol_spike_ratio', 1.2)
        self.min_score       = cfg.get('min_score', 30)
        self.take_profit_pct = cfg.get('take_profit_pct', 0.05)
        self.hard_stop_pct   = cfg.get('hard_stop_pct', 0.03)
        self._stops: dict[str, float] = {}

    @property
    def name(self) -> str:
        return "mean_reversion"

    def on_bar(self, data: dict) -> list:
        raise NotImplementedError("use evaluate() directly")

    def on_close(self) -> None:
        self._stops.clear()

    # ── Indicators ─────────────────────────────────────────────────────────
    @staticmethod
    def _rsi(close: pd.Series, period: int) -> pd.Series:
        delta = close.diff()
        gain, loss = delta.clip(lower=0), (-delta).clip(lower=0)
        avg_g = gain.ewm(span=period, adjust=False).mean()
        avg_l = loss.ewm(span=period, adjust=False).mean()
        rs = avg_g / avg_l.replace(0, np.nan)
        vals = 100.0 - 100.0 / (1.0 + rs)
        vals[avg_l == 0] = 100.0
        vals.iloc[:period] = np.nan
        return vals

    @staticmethod
    def _atr(high, low, close, period):
        prev = close.shift(1)
        tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()],
                       axis=1).max(axis=1)
        return tr.ewm(span=period, adjust=False).mean()

    @staticmethod
    def _macd(close, fast, slow, signal):
        ef = close.ewm(span=fast, adjust=False).mean()
        es = close.ewm(span=slow, adjust=False).mean()
        line = ef - es
        sig = line.ewm(span=signal, adjust=False).mean()
        return pd.DataFrame({"line": line, "signal": sig, "histogram": line - sig})

    # ── Core signal ────────────────────────────────────────────────────────
    def evaluate(self, feed: DataFeed, symbol: str,
                 positions: dict | None = None) -> dict:
        df = feed.fetch_history(symbol)
        result = {'signal': 'hold', 'score': 0.0, 'rsi': 0.0,
                  'atr': 0.0, 'close': 0.0, 'reason': ''}

        if df is None or len(df) < 30:
            result['reason'] = 'insufficient data'
            return result

        close = df['close'].astype(float)
        high, low, vol = df['high'].astype(float), df['low'].astype(float), df['volume'].astype(float)

        rsi_vals = self._rsi(close, self.rsi_period)
        atr_vals = self._atr(high, low, close, self.atr_period)
        macd_df  = self._macd(close, self.macd_fast, self.macd_slow, self.macd_signal)

        cur_rsi   = float(rsi_vals.iloc[-1])
        cur_close = float(close.iloc[-1])
        cur_atr   = float(atr_vals.iloc[-1])
        cur_hist  = float(macd_df['histogram'].iloc[-1])
        prev_hist = float(macd_df['histogram'].iloc[-2])
        prev2_hist = float(macd_df['histogram'].iloc[-3])
        macd_line = float(macd_df['line'].iloc[-1])
        sig_line  = float(macd_df['signal'].iloc[-1])

        avg_vol = vol.iloc[-self.vol_lookback:-1].mean()
        vol_ratio = float(vol.iloc[-1] / avg_vol) if avg_vol > 0 else 1.0

        result.update({'rsi': round(cur_rsi, 2), 'atr': round(cur_atr, 4),
                       'close': round(cur_close, 2)})

        if pd.isna(cur_rsi) or pd.isna(cur_atr):
            result['reason'] = 'NaN indicator'
            return result

        pos = (positions or {}).get(symbol)

        # ── SELL ──────────────────────────────────────────────────────────
        if pos:
            cost = pos.get('avg_cost', cur_close)
            stop = pos.get('stop_loss', cost * (1 - self.hard_stop_pct))
            gain_pct = (cur_close - cost) / cost if cost > 0 else 0

            if cur_rsi > self.rsi_overbought:
                result['signal'] = 'sell'
                result['reason'] = f'RSI={cur_rsi:.1f} > {self.rsi_overbought}'
                return result
            if cur_close <= stop:
                result['signal'] = 'sell'
                result['reason'] = f'stop loss: {cur_close:.2f} <= {stop:.2f}'
                return result
            if macd_line < sig_line and cur_rsi < 50 and cur_hist < prev_hist:
                result['signal'] = 'sell'
                result['reason'] = 'MACD death cross'
                return result
            if gain_pct > self.take_profit_pct and cur_rsi < 55:
                result['signal'] = 'sell'
                result['reason'] = f'take profit: +{gain_pct:.1%}'
                return result
            result['new_stop'] = max(
                cur_close - self.atr_stop_mult * cur_atr, cost * (1 - self.hard_stop_pct))
            return result

        # ── BUY ───────────────────────────────────────────────────────────
        ema30 = close.ewm(span=30, adjust=False).mean().iloc[-1]
        if cur_close < ema30:
            result['reason'] = f'price {cur_close:.2f} < EMA30 {ema30:.2f}'
            return result

        score = 0.0
        if cur_rsi < self.rsi_oversold:
            score += min(50, (self.rsi_oversold - cur_rsi) * 3)
        if cur_hist > prev_hist > prev2_hist:
            score += 15
        if cur_hist > 0:
            score += 10
        if macd_line > sig_line:
            score += 5
        if vol_ratio > 1.5:
            score += 10
        elif vol_ratio > self.vol_spike_ratio:
            score += 5

        result['score'] = round(score, 1)
        if score >= self.min_score:
            result['signal'] = 'buy'
            result['reason'] = (f'RSI={cur_rsi:.1f} hist={cur_hist:.4f} '
                               f'vol_ratio={vol_ratio:.1f} score={score:.1f}')
        else:
            result['reason'] = f'score={score:.1f} < {self.min_score}'
        return result


class PositionSizer:
    """波动率自适应仓位计算"""

    def __init__(self, base_pct=0.08, max_pct=0.15, max_positions=8):
        self.base_pct = base_pct
        self.max_pct = max_pct
        self.max_positions = max_positions

    def size(self, equity: float, price: float, atr: float) -> int:
        if price <= 0 or atr <= 0:
            return 0
        vol = atr / price
        if vol > 0.05:
            pct = self.base_pct * 0.5
        elif vol > 0.03:
            pct = self.base_pct * 0.7
        else:
            pct = self.base_pct
        amount = equity * min(pct, self.max_pct)
        lots = int(amount / (price * 100))
        return lots * 100
