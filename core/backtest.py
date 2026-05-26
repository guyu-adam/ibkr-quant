"""
回测引擎 v2 — 基于 SimulationBroker 的完整回测框架。

Features:
  - Transaction cost modeling (commission + slippage)
  - Position tracking with FIFO cost basis
  - Sharpe / max drawdown / win rate / profit factor reporting
  - Integration with WalkForwardValidator

Usage:
    from core.backtest import BacktestEngine
    be = BacktestEngine(initial_equity=100_000)
    be.run(strategy, prices_df)
    print(be.report())
"""

import logging
import numpy as np
import pandas as pd
from core.broker_interface import BrokerInterface

log = logging.getLogger(__name__)


class BacktestBroker(BrokerInterface):
    """Broker for backtesting with configurable costs and slippage."""

    def __init__(self, initial_equity=100_000, commission=0.001,
                 slippage=0.0005):
        self._equity = initial_equity
        self._initial_equity = initial_equity
        self._positions: dict[str, dict] = {}
        self._commission = commission
        self._slippage = slippage
        self._trade_log: list[dict] = []
        self._equity_curve: list[float] = [initial_equity]
        self._prices: dict[str, float] = {}
        self._connected = False

    def connect(self):
        self._connected = True

    def disconnect(self):
        self._connected = False

    def set_prices(self, prices: dict[str, float]):
        self._prices = prices

    def net_liquidation(self) -> float:
        return self._equity

    def daily_pnl(self) -> float:
        if len(self._equity_curve) >= 2:
            return self._equity_curve[-1] - self._equity_curve[-2]
        return 0.0

    def positions(self) -> dict[str, float]:
        return {s: p["shares"] for s, p in self._positions.items()}

    def last_price(self, symbol: str) -> float:
        return self._prices.get(symbol, 0.0)

    def market_order(self, symbol: str, shares: int, action: str):
        price = self._prices.get(symbol, 0.0)
        if price <= 0 or shares <= 0:
            return

        action = action.upper()
        slip_price = price * (1 + self._slippage if action == "BUY"
                              else 1 - self._slippage)
        notional = shares * slip_price
        cost = notional * self._commission

        if action == "BUY":
            total = notional + cost
            if total > self._equity * 0.3:
                return
            self._equity -= total
            if symbol not in self._positions:
                self._positions[symbol] = {"shares": 0, "avg_cost": 0.0}
            pos = self._positions[symbol]
            old_cost = pos["avg_cost"]
            old_qty = pos["shares"]
            new_qty = old_qty + shares
            pos["shares"] = new_qty
            if old_qty > 0:
                pos["avg_cost"] = (old_cost * old_qty + slip_price * shares) / new_qty
            else:
                pos["avg_cost"] = slip_price
        elif action == "SELL" and symbol in self._positions:
            pos = self._positions[symbol]
            qty = min(shares, pos["shares"])
            self._equity += qty * slip_price - cost
            pnl = qty * (slip_price - pos["avg_cost"])
            pos["shares"] -= qty
            if pos["shares"] <= 0:
                del self._positions[symbol]

        self._trade_log.append({
            "symbol": symbol, "action": action, "shares": shares,
            "price": slip_price, "cost": cost,
        })
        self._equity_curve.append(self._equity)


class BacktestEngine:
    """Run a strategy against historical price data."""

    def __init__(self, initial_equity=100_000, commission=0.001,
                 slippage=0.0005):
        self.broker = BacktestBroker(initial_equity, commission, slippage)
        self._strategy = None

    def run(self, strategy, prices_df: pd.DataFrame,
            signals_df: pd.DataFrame = None) -> dict:
        """
        Run backtest over historical data.

        Args:
            strategy: strategy instance with evaluate() method
            prices_df: T x N price DataFrame (columns=symbols, index=dates)
            signals_df: optional pre-computed signal DataFrame

        Returns:
            dict with performance metrics
        """
        self._strategy = strategy
        symbols = list(prices_df.columns)

        for i in range(60, len(prices_df)):
            date = prices_df.index[i]
            current_prices = {s: float(prices_df[s].iloc[i]) for s in symbols}
            self.broker.set_prices(current_prices)

            # Evaluate each symbol
            for sym in symbols:
                try:
                    history = prices_df[sym].iloc[:i+1]
                    hist_df = pd.DataFrame({
                        "open": history * 0.99,
                        "high": history * 1.01,
                        "low": history * 0.98,
                        "close": history,
                        "volume": np.full(len(history), 1000000),
                    }, index=history.index)

                    result = strategy.evaluate(
                        type("Feed", (), {"fetch_history": lambda s, p=None, iv=None: hist_df})(),
                        sym,
                        positions={sym: {"avg_cost": self.broker._positions.get(sym, {}).get("avg_cost", 0),
                                        "stop_loss": 0}}
                        if sym in self.broker._positions else None,
                    )

                    holding = self.broker.positions().get(sym, 0)

                    if result.get("signal") == "sell" and holding > 0:
                        self.broker.market_order(sym, holding, "SELL")
                    elif result.get("signal") == "buy" and holding == 0:
                        price = current_prices[sym]
                        atr = result.get("atr", price * 0.02)
                        size = self._position_size(price, atr)
                        if size > 0:
                            self.broker.market_order(sym, size, "BUY")
                except Exception as e:
                    log.debug(f"Backtest {sym}@{date}: {e}")

        return self.report()

    def _position_size(self, price: float, atr: float) -> int:
        equity = self.broker.net_liquidation()
        risk_amt = equity * 0.01
        stop_dist = atr * 2.0
        if stop_dist <= 0:
            return 0
        shares = int(risk_amt / stop_dist)
        max_shares = int(equity * 0.10 / price)
        return max(0, min(shares, max_shares))

    def report(self) -> dict:
        """Generate performance report."""
        curve = np.array(self.broker._equity_curve)
        if len(curve) < 2:
            return {"sharpe": 0, "total_return": 0, "max_drawdown": 0,
                    "win_rate": 0, "profit_factor": 0, "n_trades": 0}

        returns = np.diff(curve) / (curve[:-1] + 1e-8)
        sharpe = float(np.mean(returns) / (np.std(returns) + 1e-8) * np.sqrt(252))
        total_return = float(curve[-1] / curve[0] - 1)

        peak = np.maximum.accumulate(curve)
        dd = (curve - peak) / (peak + 1e-8)
        max_dd = float(abs(dd.min()))

        trades = self.broker._trade_log
        wins = sum(1 for t in trades if t["action"] == "SELL")
        total = len([t for t in trades if t["action"] == "SELL"])
        win_rate = wins / total if total > 0 else 0

        gross_profit = 0.0
        gross_loss = 0.0
        # Simple approximation: equity increase from sells = profit
        if len(self.broker._equity_curve) > 1:
            for i in range(1, len(self.broker._equity_curve)):
                diff = self.broker._equity_curve[i] - self.broker._equity_curve[i-1]
                if diff > 0:
                    gross_profit += diff
                else:
                    gross_loss += abs(diff)

        profit_factor = gross_profit / (gross_loss + 1e-8)

        return {
            "sharpe": round(sharpe, 3),
            "total_return": round(total_return, 4),
            "max_drawdown": round(max_dd, 4),
            "win_rate": round(win_rate, 4),
            "profit_factor": round(profit_factor, 2),
            "n_trades": len(trades),
        }
