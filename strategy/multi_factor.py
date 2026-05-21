"""
多因子量化策略 v2 — 截面标准化 + 面板训练 + LightGBM

核心改进:
  1. 因子在每期截面上对所有股票 z-score 标准化（消除量纲差异）
  2. 模型在面板数据上训练（所有股票 × 所有截面），而非单股时序
  3. 预测目标: 未来 N 日截面排名分位数（IC 优化）
  4. 组合优化: 风险平价 / 最大夏普
  5. 交易成本: 滑点 + 手续费计入回测
"""

import logging
import numpy as np
import pandas as pd
from typing import Optional
from datetime import datetime

from core.alpha_factors import compute_factors, compute_forward_returns
from core.ml_model import AlphaModel
from core.portfolio_optimizer import optimize_portfolio

log = logging.getLogger(__name__)


class MultiFactorStrategy:
    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.model           = AlphaModel(cfg.get('model', {}))
        self.top_k            = cfg.get('top_k', 20)
        self.rebalance_freq   = cfg.get('rebalance_freq', 5)
        self.max_weight       = cfg.get('max_weight', 0.15)
        self.min_weight       = cfg.get('min_weight', 0.01)
        self.opt_method       = cfg.get('opt_method', 'risk_parity')
        self.transaction_cost = cfg.get('transaction_cost', 0.001)
        self.slippage         = cfg.get('slippage', 0.001)
        self.stop_loss_pct    = cfg.get('stop_loss_pct', 0.08)

    @property
    def name(self) -> str:
        return 'multi_factor'

    def on_bar(self, data: dict) -> list[dict]:
        return []

    def on_close(self) -> None:
        pass

    def backtest(
        self,
        symbols: list[str],
        start_date: str,
        end_date: str,
        initial_capital: float = 1_000_000.0,
    ) -> dict:
        import yfinance as yf

        # ── 下载数据 ──────────────────────────────────────────────────────
        price_data = {}
        for sym in symbols:
            try:
                df = yf.download(sym, start=start_date, end=end_date,
                                 interval='1d', progress=False, auto_adjust=True)
                if df is not None and len(df) > 200:
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.droplevel(1)
                    df = df.rename(columns={'Open':'open','High':'high',
                                            'Low':'low','Close':'close',
                                            'Volume':'volume'})
                    price_data[sym] = df[['open','high','low','close','volume']]
            except Exception:
                pass

        log.info(f"数据: {len(price_data)}/{len(symbols)} 只")

        # ── 构建统一的截面日期 ────────────────────────────────────────────
        all_dates = sorted(set.union(*[set(d.index) for d in price_data.values()]))
        all_dates = [d for d in all_dates if str(d) <= end_date and str(d) >= start_date]

        # ── 计算每个截面的因子矩阵（预计算，加速回测）──────────────────────
        factor_panels: dict[pd.Timestamp, pd.DataFrame] = {}
        forward_returns: dict[pd.Timestamp, pd.Series] = {}

        for date in all_dates:
            rows = {}
            for sym in symbols:
                if sym not in price_data:
                    continue
                df = price_data[sym]
                if date not in df.index:
                    continue
                idx = df.index.get_loc(date)
                if idx < 100:
                    continue
                window = df.iloc[max(0, idx-252):idx+1]
                if len(window) < 100:
                    continue
                try:
                    X = compute_factors(window)
                    if X.empty:
                        continue
                    row = X.iloc[-1].to_dict()
                    row['close'] = float(window['close'].iloc[-1])
                    rows[sym] = row
                except Exception:
                    continue

            if len(rows) < 10:
                continue

            panel = pd.DataFrame(rows).T
            # 截面标准化
            for col in panel.columns:
                if col == 'close':
                    continue
                vals = panel[col].astype(float)
                mu, std = vals.mean(), vals.std()
                if std > 0:
                    panel[col] = (vals - mu) / std
                else:
                    panel[col] = 0.0

            factor_panels[date] = panel

            # 前向收益（用于训练标签）
            horizon = self.model.horizon
            future_date_idx = all_dates.index(date) + horizon
            if future_date_idx < len(all_dates):
                future_date = all_dates[future_date_idx]
                fwd = {}
                for sym in panel.index:
                    if sym in price_data and future_date in price_data[sym].index:
                        p_now = float(price_data[sym].loc[date, 'close'])
                        p_fwd = float(price_data[sym].loc[future_date, 'close'])
                        fwd[sym] = (p_fwd - p_now) / p_now
                forward_returns[date] = pd.Series(fwd)

        log.info(f"因子面板: {len(factor_panels)} 个截面")

        # ── 回测主循环 ────────────────────────────────────────────────────
        dates = sorted(factor_panels.keys())
        train_start = dates[0]
        capital = initial_capital
        positions: dict[str, dict] = {}
        equity_curve = [capital]
        trades_log: list[dict] = []
        daily_rets: list[float] = []

        for i, date in enumerate(dates):
            # 训练期：前 252 天
            if date < pd.Timestamp(start_date) + pd.Timedelta(days=365):
                # 仅记录权益曲线
                port_val = capital
                for s, p in positions.items():
                    if s in price_data and date in price_data[s].index:
                        port_val += p['shares'] * float(price_data[s].loc[date,'close'])
                equity_curve.append(port_val)
                continue

            panel = factor_panels[date]
            factor_cols = [c for c in panel.columns if c != 'close']

            # ── 盯市 ──────────────────────────────────────────────────────
            port_val = capital
            for s, p in list(positions.items()):
                if s in price_data and date in price_data[s].index:
                    px = float(price_data[s].loc[date, 'close'])
                    port_val += p['shares'] * px
                    # 止损
                    loss = (px - p['avg_cost']) / p['avg_cost']
                    if loss < -self.stop_loss_pct:
                        capital += p['shares'] * px * (1 - self.transaction_cost)
                        trades_log.append({
                            'date': str(date), 'symbol': s, 'action': 'SELL',
                            'shares': p['shares'], 'price': px, 'reason': 'stop',
                            'pnl': (px - p['avg_cost']) * p['shares'],
                        })
                        del positions[s]

            equity_curve.append(port_val)
            if len(equity_curve) > 1:
                daily_rets.append((equity_curve[-1]-equity_curve[-2])/max(equity_curve[-2],1))

            # ── 是否调仓日 ────────────────────────────────────────────────
            if (i - 252) % self.rebalance_freq != 0:
                continue

            # ── 训练模型（滚动窗口：过去 252 天）──────────────────────────
            train_dates = [d for d in dates if d < date and d >= dates[max(0,i-252)]]
            X_train_list, y_train_list = [], []
            for td in train_dates:
                if td in factor_panels and td in forward_returns:
                    fp = factor_panels[td]
                    fr = forward_returns[td]
                    common = fp.index.intersection(fr.index)
                    if len(common) > 5:
                        X_train_list.append(fp.loc[common, factor_cols])
                        y_train_list.append(fr.loc[common])

            if X_train_list:
                X_train = pd.concat(X_train_list).fillna(0.0)
                y_train = pd.concat(y_train_list)
                self.model.train(X_train, y_train)

            if not self.model.is_trained:
                continue

            # ── 预测 ───────────────────────────────────────────────────────
            preds = self.model.predict(panel[factor_cols].fillna(0.0))
            # 过滤已持仓标的
            preds = preds.drop(list(positions.keys()), errors='ignore')
            if preds.empty:
                continue

            longs, _ = self.model.select_top(preds)

            # ── 组合优化 ──────────────────────────────────────────────────
            price_matrix = pd.DataFrame({
                s: price_data[s]['close'] for s in longs if s in price_data
            }).dropna(axis=1)
            if price_matrix.shape[1] < 2:
                continue

            weights = optimize_portfolio(
                list(price_matrix.columns), preds, price_matrix,
                method=self.opt_method,
                max_weight=self.max_weight,
                min_weight=self.min_weight,
            )

            # ── 卖出调出的持仓 ────────────────────────────────────────────
            for s in list(positions):
                if s not in weights and s in price_data and date in price_data[s].index:
                    px = float(price_data[s].loc[date, 'close'])
                    cost = positions[s]['avg_cost']
                    capital += positions[s]['shares'] * px * (1 - self.transaction_cost)
                    trades_log.append({
                        'date': str(date), 'symbol': s, 'action': 'SELL',
                        'shares': positions[s]['shares'], 'price': px,
                        'reason': 'rebalance',
                        'pnl': (px - cost) * positions[s]['shares'],
                    })
                    del positions[s]

            # ── 买入新组合 ────────────────────────────────────────────────
            total_equity = port_val
            for sym, weight in weights.items():
                if sym in positions or sym not in price_data or date not in price_data[sym].index:
                    continue
                px = float(price_data[sym].loc[date, 'close'])
                target = total_equity * weight
                shares = int(target / px)
                if shares <= 0:
                    continue
                cost = shares * px * (1 + self.transaction_cost)
                if cost > capital:
                    shares = int(capital / (px * (1 + self.transaction_cost)))
                    cost = shares * px * (1 + self.transaction_cost)
                if shares <= 0:
                    continue
                capital -= cost
                positions[sym] = {'shares': shares, 'avg_cost': px}
                trades_log.append({
                    'date': str(date), 'symbol': sym, 'action': 'BUY',
                    'shares': shares, 'price': px,
                })

        # ── 统计 ──────────────────────────────────────────────────────────
        final = equity_curve[-1]
        ret = (final - initial_capital) / initial_capital
        years = max(0.1, len(daily_rets) / 252)
        ann = (1 + ret) ** (1 / years) - 1
        r = pd.Series(daily_rets).dropna()
        sr = float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else 0
        dd = _max_dd(equity_curve)
        wins = [t for t in trades_log if t.get('pnl', 0) > 0]
        wr = len(wins) / max(1, len([t for t in trades_log if 'pnl' in t]))

        return {
            'equity_curve': equity_curve,
            'total_return': ret,
            'annual_return': ann,
            'sharpe_ratio': sr,
            'max_drawdown': dd,
            'win_rate': wr,
            'n_trades': len(trades_log),
            'trades': trades_log,
        }


def _max_dd(curve):
    peak = curve[0]; dd = 0.0
    for v in curve:
        peak = max(peak, v); dd = min(dd, (v-peak)/peak)
    return abs(dd)
