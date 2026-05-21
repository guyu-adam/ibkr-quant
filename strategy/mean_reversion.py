"""
均值回归策略 — RSI 超卖反弹 + MACD 底背离确认 + 成交量验证

纯信号生成，不包含任何执行逻辑。可用于：
  - IBKR 实盘/模拟盘 (main.py)
  - A股纸上交易 (paper_trading/)
  - 离线回测 (backtest.py)

使用方式:
    from strategy.mean_reversion import MeanReversionStrategy
    strategy = MeanReversionStrategy(config)
    signal = strategy.evaluate(symbol, data_feed)
"""

import logging
from typing import Optional
import pandas as pd
import numpy as np

from core.strategy_base import BaseStrategy
from core.data_feed import DataFeed

logger = logging.getLogger(__name__)


class MeanReversionStrategy(BaseStrategy):
    """
    RSI 超卖反弹 + MACD 底背离 + 成交量确认

    买入: RSI < oversold + MACD histogram 收窄 + 成交量放大 → 评分 > 阈值
    卖出: RSI > overbought / ATR 移动止损 / MACD 死叉 / 获利回落
    """

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.rsi_period       = cfg.get('rsi_period', 14)
        self.rsi_oversold     = cfg.get('rsi_oversold', 30)
        self.rsi_overbought   = cfg.get('rsi_overbought', 70)
        self.atr_period       = cfg.get('atr_period', 14)
        self.atr_stop_mult    = cfg.get('atr_stop_mult', 2.0)
        self.macd_fast        = cfg.get('macd_fast', 12)
        self.macd_slow        = cfg.get('macd_slow', 26)
        self.macd_signal      = cfg.get('macd_signal', 9)
        self.vol_lookback     = cfg.get('vol_lookback', 20)
        self.vol_spike_ratio  = cfg.get('vol_spike_ratio', 1.2)
        self.min_score        = cfg.get('min_score', 30)
        self.take_profit_pct  = cfg.get('take_profit_pct', 0.05)
        self.hard_stop_pct    = cfg.get('hard_stop_pct', 0.03)
        self.name_str         = cfg.get('name', 'mean_reversion')

        # Internal cache for each symbol
        self._stops: dict[str, float] = {}  # symbol → trailing_stop_price

    # ── BaseStrategy interface ───────────────────────────────────────────────
    @property
    def name(self) -> str:
        return self.name_str

    def on_bar(self, data: dict) -> list[dict]:
        """
        每根 bar 调用。data 应包含:
          symbol, open, high, low, close, volume, positions (dict), equity (float)
        返回 [signal_dict, ...]
        """
        raise NotImplementedError("use evaluate() directly for this strategy")

    def on_close(self) -> None:
        self._stops.clear()

    # ── Indicator helpers ────────────────────────────────────────────────────
    @staticmethod
    def _rsi(close: pd.Series, period: int) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_g = gain.ewm(span=period, adjust=False).mean()
        avg_l = loss.ewm(span=period, adjust=False).mean()
        rs = avg_g / avg_l.replace(0, np.nan)
        vals = 100.0 - 100.0 / (1.0 + rs)
        vals[avg_l == 0] = 100.0
        vals.iloc[:period] = np.nan
        return vals

    @staticmethod
    def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        return tr.ewm(span=period, adjust=False).mean()

    @staticmethod
    def _macd(close: pd.Series, fast: int, slow: int, signal: int) -> pd.DataFrame:
        ema_f = close.ewm(span=fast, adjust=False).mean()
        ema_s = close.ewm(span=slow, adjust=False).mean()
        line = ema_f - ema_s
        sig = line.ewm(span=signal, adjust=False).mean()
        return pd.DataFrame({"line": line, "signal": sig, "histogram": line - sig})

    # ── Core signal logic ────────────────────────────────────────────────────
    def evaluate(self, feed: DataFeed, symbol: str,
                 positions: dict[str, dict] | None = None) -> dict:
        """
        评估单个标的，返回信号字典。

        Args:
            feed: 数据源
            symbol: 标的代码 (如 '000001' 或 'AAPL')
            positions: 当前持仓 {symbol: {shares, avg_cost, stop_loss, ...}}

        Returns:
            {
                'signal': 'buy' | 'sell' | 'hold',
                'score': 0-100 评分,
                'rsi': float,
                'atr': float,
                'close': float,
                'reason': str,
            }
        """
        df = feed.fetch_history(symbol)
        result = {'signal': 'hold', 'score': 0.0, 'rsi': 0.0,
                  'atr': 0.0, 'close': 0.0, 'reason': ''}

        if df is None or len(df) < 30:
            result['reason'] = 'insufficient data'
            return result

        close = df['close'].astype(float)
        high  = df['high'].astype(float)
        low   = df['low'].astype(float)
        vol   = df['volume'].astype(float)

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

        # Volume spike
        avg_vol = vol.iloc[-self.vol_lookback:-1].mean()
        vol_ratio = float(vol.iloc[-1] / avg_vol) if avg_vol > 0 else 1.0

        result.update({'rsi': round(cur_rsi, 2), 'atr': round(cur_atr, 4),
                       'close': round(cur_close, 2)})

        if pd.isna(cur_rsi) or pd.isna(cur_atr):
            result['reason'] = 'NaN indicator'
            return result

        pos = (positions or {}).get(symbol)

        # ═══ 卖出判断 ═══════════════════════════════════════════════════════
        if pos:
            cost   = pos.get('avg_cost', cur_close)
            stop   = pos.get('stop_loss', cost * (1 - self.hard_stop_pct))
            gain_pct = (cur_close - cost) / cost if cost > 0 else 0

            # RSI 超买
            if cur_rsi > self.rsi_overbought:
                result['signal'] = 'sell'
                result['reason'] = f'RSI={cur_rsi:.1f} > {self.rsi_overbought}'
                return result

            # 触发止损
            if cur_close <= stop:
                result['signal'] = 'sell'
                result['reason'] = f'stop loss hit: close={cur_close:.2f} <= stop={stop:.2f}'
                return result

            # MACD 死叉
            if macd_line < sig_line and cur_rsi < 50 and cur_hist < prev_hist:
                result['signal'] = 'sell'
                result['reason'] = 'MACD death cross'
                return result

            # 获利回落
            if gain_pct > self.take_profit_pct and cur_rsi < 55:
                result['signal'] = 'sell'
                result['reason'] = f'take profit: +{gain_pct:.1%}'
                return result

            # 更新移动止损
            result['new_stop'] = max(
                cur_close - self.atr_stop_mult * cur_atr,
                cost * (1 - self.hard_stop_pct),
            )

        # ═══ 买入评分 ═══════════════════════════════════════════════════════
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
        result['vol_ratio'] = round(vol_ratio, 2)

        if score >= self.min_score and not pos:
            result['signal'] = 'buy'
            result['reason'] = (
                f'RSI={cur_rsi:.1f} MACD_hist={cur_hist:.4f} '
                f'vol_ratio={vol_ratio:.1f} score={score:.1f}'
            )
        elif not pos:
            result['reason'] = f'score={score:.1f} < {self.min_score}'

        return result

    def trailing_stop(self, symbol: str, close: float, atr: float,
                      cost: float) -> float:
        """计算 ATR 移动止损价"""
        return max(close - self.atr_stop_mult * atr, cost * (1 - self.hard_stop_pct))


class PositionSizer:
    """波动率自适应仓位计算"""

    def __init__(self, base_pct: float = 0.08, max_pct: float = 0.15,
                 max_positions: int = 8):
        self.base_pct = base_pct
        self.max_pct = max_pct
        self.max_positions = max_positions

    def size(self, equity: float, price: float, atr: float) -> int:
        """
        返回建议股数（A股已折算为 100 股整手）。

        Args:
            equity: 账户总资产
            price:  当前股价
            atr:    ATR 值
        """
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
        lots = int(amount / (price * 100))  # A 股 100 股 / 手
        return lots * 100
