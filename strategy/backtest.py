"""
快速回测：用 yfinance 拉历史数据验证策略逻辑
不依赖 IBKR 连接，纯离线运行

用法：
    conda activate quant
    python -m strategy.backtest
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import yfinance as yf

from strategy.signals import compute_indicators, generate_signal
from config.settings  import WATCHLIST, RSI_OVERSOLD, RSI_OVERBOUGHT, STOP_LOSS_ATR_MULT


def run_backtest(symbol: str, start="2022-01-01", end="2025-01-01",
                 initial_equity=10_000.0) -> dict:
    df = yf.download(symbol, start=start, end=end, interval="1d", progress=False)
    if df.empty:
        return {}

    df.columns = [c.lower() for c in df.columns]
    df = df.rename(columns={"adj close": "close"})[["open","high","low","close","volume"]]
    df = compute_indicators(df)
    df["signal"] = 0

    # 生成信号列
    for i in range(40, len(df)):
        s = generate_signal(df.iloc[:i+1])["signal"]
        df.iloc[i, df.columns.get_loc("signal")] = s

    # 模拟持仓与 PnL
    equity   = initial_equity
    position = 0
    entry_px = 0.0
    stop_px  = 0.0
    equity_curve = [equity]
    trades = []

    for i, row in df.iterrows():
        price = row["close"]
        sig   = row["signal"]

        # 止损
        if position > 0 and price <= stop_px:
            pnl = (price - entry_px) * position
            equity += pnl
            trades.append({"type":"stop","pnl":pnl})
            position = 0

        elif position < 0 and price >= stop_px:
            pnl = (entry_px - price) * abs(position)
            equity += pnl
            trades.append({"type":"stop","pnl":pnl})
            position = 0

        # 平仓
        if position > 0 and sig == -1:
            pnl = (price - entry_px) * position
            equity += pnl
            trades.append({"type":"close","pnl":pnl})
            position = 0

        elif position < 0 and sig == 1:
            pnl = (entry_px - price) * abs(position)
            equity += pnl
            trades.append({"type":"close","pnl":pnl})
            position = 0

        # 开仓
        if position == 0 and sig != 0:
            atr_val   = row["atr"]
            stop_dist = atr_val * STOP_LOSS_ATR_MULT
            shares    = max(1, int(equity * 0.01 / stop_dist)) if stop_dist > 0 else 0
            shares    = min(shares, int(equity * 0.10 / price))
            if shares > 0:
                position = shares if sig == 1 else -shares
                entry_px = price
                stop_px  = price - stop_dist if sig == 1 else price + stop_dist

        equity_curve.append(equity)

    # 统计
    tdf = pd.DataFrame(trades) if trades else pd.DataFrame(columns=["type","pnl"])
    wins  = (tdf["pnl"] > 0).sum() if len(tdf) else 0
    total = len(tdf)
    rets  = pd.Series(equity_curve).pct_change().dropna()
    sharpe = rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else 0

    result = {
        "symbol":       symbol,
        "total_trades": total,
        "win_rate":     wins / total if total else 0,
        "final_equity": equity,
        "total_return": (equity - initial_equity) / initial_equity,
        "sharpe":       sharpe,
        "max_drawdown": _max_drawdown(equity_curve),
        "equity_curve": equity_curve,
    }
    return result


def _max_drawdown(curve: list) -> float:
    peak = curve[0]
    dd = 0.0
    for v in curve:
        peak = max(peak, v)
        dd   = min(dd, (v - peak) / peak)
    return dd


def plot_results(results: list):
    fig, axes = plt.subplots(len(results), 1, figsize=(12, 4 * len(results)))
    if len(results) == 1:
        axes = [axes]

    for ax, r in zip(axes, results):
        curve = r["equity_curve"]
        ax.plot(curve, linewidth=1.2)
        ax.axhline(curve[0], color="gray", linestyle="--", linewidth=0.8)
        ax.set_title(
            f"{r['symbol']}  ret={r['total_return']:.1%}  "
            f"sharpe={r['sharpe']:.2f}  dd={r['max_drawdown']:.1%}  "
            f"trades={r['total_trades']}  win={r['win_rate']:.0%}",
            fontsize=10
        )
        ax.set_ylabel("Equity ($)")
        ax.grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig("logs/backtest_result.png", dpi=150)
    print("Saved: logs/backtest_result.png")


if __name__ == "__main__":
    import os; os.makedirs("logs", exist_ok=True)
    results = []
    for sym in ["SPY", "QQQ", "AAPL", "NVDA"]:
        r = run_backtest(sym)
        if r:
            results.append(r)
            print(f"{r['symbol']:6}  ret={r['total_return']:+.1%}  "
                  f"sharpe={r['sharpe']:.2f}  dd={r['max_drawdown']:.1%}  "
                  f"trades={r['total_trades']}  win={r['win_rate']:.0%}")
    plot_results(results)
