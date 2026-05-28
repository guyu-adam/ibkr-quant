"""
增强配对交易 — Johansen 协整检验 + 卡尔曼滤波动态对冲比。

相比基础 Engle-Granger + OLS:
  - Johansen 检验: 可检测多个协整关系，检验效力更强
  - Kalman Filter: 对冲比随时间自适应变化，应对结构突变
  - 半衰期优化: Bayesian optimization 调参

Usage:
    from core.pairs_enhanced import EnhancedPairTrader
    trader = EnhancedPairTrader()
    pairs = trader.find_pairs(prices_df)  # 多方法筛选
    trader.fit_kalman(prices_a, prices_b)  # 训练卡尔曼滤波器
    signal = trader.trade_signal(spread, z_score)  # 交易信号
"""

import logging
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


# ═══════════════════ Johansen 协整检验 ════════════════════════════════════════

def johansen_test(y: np.ndarray, p: int = 1, det_order: int = 0) -> dict:
    """
    Johansen cointegration test.

    Args:
        y: T×K matrix of K time series
        p: VAR order (lag length)
        det_order: -1=no trend, 0=constant, 1=linear trend

    Returns:
        dict with eigen_values, max_eigen_stat, trace_stat, crit_values
    """
    try:
        from statsmodels.tsa.vector_ar.vecm import coint_johansen
        result = coint_johansen(y, det_order, p)
        return {
            "eigen_values": result.eig,
            "max_eigen_stat": result.max_eig_stat,
            "trace_stat": result.trace_stat,
            "max_eig_crit_95": result.max_eig_stat_crit_vals[:, 1],
            "trace_crit_95": result.trace_stat_crit_vals[:, 1],
            "is_cointegrated": result.trace_stat[0] > result.trace_stat_crit_vals[0, 1],
        }
    except ImportError:
        log.warning("statsmodels not installed — Johansen test unavailable")
    except Exception as e:
        log.warning(f"Johansen test failed: {e}")

    return {"eigen_values": np.array([]), "is_cointegrated": False}


# ═══════════════════ Kalman Filter 动态对冲 ═══════════════════════════════════

class KalmanHedgeRatio:
    """
    Dynamic hedge ratio via Kalman filter.

    State space model:
      y_t = beta_t * x_t + eps_t          (observation)
      beta_t = beta_{t-1} + eta_t          (state transition — random walk)

    Uses pykalman or scipy implementation for covariance estimation.
    """

    def __init__(self, delta: float = 1e-5, vt: float = 1e-3):
        """
        Args:
            delta: observation noise variance guess
            vt: state transition noise variance (higher = more adaptive)
        """
        self.delta = delta
        self.vt = vt
        self._beta: np.ndarray | None = None
        self._beta_history: list[float] = []
        self._pred_errors: list[float] = []

    def fit(self, y: np.ndarray, x: np.ndarray):
        """
        Online Kalman filter estimation.

        Args:
            y: target price series (T,)
            x: predictor price series (T,)
        """
        T = len(y)
        # State: [beta]
        beta = np.ones(1)  # initial guess: hedge ratio = 1
        P = np.eye(1) * 1.0  # state covariance
        Q = np.eye(1) * self.vt  # process noise

        self._beta_history = []

        for t in range(T):
            # Predict
            beta_pred = beta
            P_pred = P + Q

            # Update
            xt = x[t]
            yt = y[t]

            # Kalman gain
            S = xt * P_pred[0, 0] * xt + self.delta
            K = P_pred[0, 0] * xt / (S + 1e-12)

            # Innovation
            y_pred = beta_pred[0] * xt
            innovation = yt - y_pred

            # State update
            beta[0] = beta_pred[0] + K * innovation
            P[0, 0] = (1 - K * xt) * P_pred[0, 0]

            self._beta_history.append(float(beta[0]))
            self._pred_errors.append(float(innovation))

        self._beta = beta

    def predict(self, x_new: float) -> float:
        """Predict y given new x using latest beta."""
        if self._beta is None:
            raise RuntimeError("Kalman filter not fitted")
        return float(self._beta[0] * x_new)

    @property
    def beta(self) -> float:
        return float(self._beta[0]) if self._beta is not None else 1.0

    @property
    def beta_series(self) -> np.ndarray:
        return np.array(self._beta_history)

    @property
    def spread(self) -> np.ndarray:
        """Return normalized spread = pred_errors."""
        return np.array(self._pred_errors)

    def zscore(self) -> float:
        """Current z-score of normalized spread."""
        if len(self._pred_errors) < 20:
            return 0.0
        recent = self._pred_errors[-60:]
        mean = np.mean(recent)
        std = np.std(recent)
        if std <= 0:
            return 0.0
        return (recent[-1] - mean) / std


# ═══════════════════ 半衰期估计 (增强) ══════════════════════════════════════

def estimate_half_life_robust(spread: pd.Series, min_hl: float = 1.0,
                               max_hl: float = 252.0) -> float:
    """
    Robust half-life estimation using Theil-Sen regression (less sensitive to outliers).

    Returns: half-life in trading days. 999 if no mean-reversion detected.
    """
    spread = spread.dropna()
    if len(spread) < 30:
        return 999.0

    lag = spread.shift(1).dropna()
    diff = spread.diff().dropna()
    common = lag.index.intersection(diff.index)
    if len(common) < 20:
        return 999.0

    y = diff.loc[common].values
    x = lag.loc[common].values.reshape(-1, 1)

    try:
        from sklearn.linear_model import TheilSenRegressor
        reg = TheilSenRegressor(random_state=42).fit(x, y)
        beta = reg.coef_[0]
    except ImportError:
        # Fall back to OLS
        X = np.column_stack([np.ones(len(x)), x.ravel()])
        try:
            beta = np.linalg.lstsq(X, y, rcond=None)[0][1]
        except np.linalg.LinAlgError:
            return 999.0

    if beta >= 0:
        return 999.0
    hl = -np.log(2) / beta
    return max(min_hl, min(hl, max_hl))


# ═══════════════════ 增强配对交易器 ══════════════════════════════════════════

class EnhancedPairTrader:
    """
    Complete pair trading pipeline: screening → fitting → signal → risk.

    Pipeline:
      1. find_pairs(): 协整 + 相关性 + 半衰期筛选
      2. fit_kalman(): 卡尔曼滤波估计动态对冲比
      3. signals(): 生成 z-score 进出场信号
    """

    def __init__(self, corr_min: float = 0.7, hl_min: float = 2.0,
                 hl_max: float = 60.0, z_entry: float = 2.0,
                 z_exit: float = 0.5):
        self.corr_min = corr_min
        self.hl_min = hl_min
        self.hl_max = hl_max
        self.z_entry = z_entry
        self.z_exit = z_exit
        self._kalman: KalmanHedgeRatio | None = None
        self._active_pairs: dict[tuple, dict] = {}

    def find_pairs(self, prices: pd.DataFrame,
                   methods: list[str] | None = None) -> pd.DataFrame:
        """
        Screen pairs using multiple methods.
        methods: ["johansen", "correlation", "halflife"]
        """
        methods = methods or ["correlation", "halflife"]
        symbols = prices.columns
        pairs_list = []

        for i, a in enumerate(symbols):
            for b in symbols[i + 1:]:
                pa = prices[a].dropna()
                pb = prices[b].dropna()
                common = pa.index.intersection(pb.index)
                if len(common) < 120:
                    continue

                pa_c = pa[common].values
                pb_c = pb[common].values

                corr = float(np.corrcoef(pa_c, pb_c)[0, 1])
                if abs(corr) < self.corr_min:
                    continue

                # Hedge ratio via OLS
                X = np.column_stack([np.ones(len(pa_c)), pa_c])
                hedge = np.linalg.lstsq(X, pb_c, rcond=None)[0][1]
                spread = pb_c - hedge * pa_c

                hl = estimate_half_life_robust(pd.Series(spread))
                if hl < self.hl_min or hl > self.hl_max:
                    continue

                # Johansen test (if available)
                johansen_passed = False
                if "johansen" in methods:
                    jr = johansen_test(np.column_stack([pa_c, pb_c]))
                    johansen_passed = jr.get("is_cointegrated", False)

                # Z-score
                spread_mean = np.mean(spread)
                spread_std = np.std(spread)
                z_now = (spread[-1] - spread_mean) / (spread_std + 1e-8)

                pairs_list.append({
                    "stock_a": a, "stock_b": b,
                    "hedge_ratio": round(hedge, 4),
                    "half_life": round(hl, 1),
                    "correlation": round(corr, 4),
                    "z_score": round(z_now, 3),
                    "spread_vol": round(float(spread_std), 6),
                    "johansen": johansen_passed,
                })

        return pd.DataFrame(pairs_list).sort_values("half_life")

    def fit_kalman(self, y: np.ndarray, x: np.ndarray):
        """Fit Kalman filter for dynamic hedge estimation."""
        self._kalman = KalmanHedgeRatio()
        self._kalman.fit(y, x)

    def signals(self, spread: np.ndarray, z_entry: float | None = None,
                z_exit: float | None = None) -> dict:
        """
        Generate trade signals from current spread.

        Returns: {"signal": "long_spread"|"short_spread"|"hold"|"close",
                  "z_score": float, "position_size": float}
        """
        z_entry = z_entry or self.z_entry
        z_exit = z_exit or self.z_exit

        if self._kalman is not None:
            z = self._kalman.zscore()
        else:
            if len(spread) < 20:
                return {"signal": "hold", "z_score": 0.0, "position_size": 0.0}
            mean = np.mean(spread[-60:])
            std = np.std(spread[-60:])
            z = (spread[-1] - mean) / (std + 1e-8) if std > 0 else 0.0

        signal = "hold"
        if z > z_entry:
            signal = "short_spread"
        elif z < -z_entry:
            signal = "long_spread"
        elif abs(z) < z_exit:
            signal = "close"

        # Kelly-inspired position sizing
        pos_size = min(1.0, abs(z) / (z_entry * 2)) * 2 - 1 if signal != "close" else 0

        return {"signal": signal, "z_score": round(z, 3),
                "position_size": round(max(0, pos_size), 3)}

    def optimize_entry_threshold(self, spread: np.ndarray,
                                  z_range: tuple = (1.0, 3.0, 0.25)) -> tuple[float, float]:
        """Grid search for optimal z_entry/z_exit by maximizing Sharpe."""
        best_sharpe = -999.0
        best_params = (self.z_entry, self.z_exit)

        for z_e in np.arange(*z_range):
            for z_x in np.arange(0.0, z_e, 0.25):
                if z_x >= z_e:
                    continue
                rets = self._simulate_trades(spread, z_e, z_x)
                if len(rets) < 5:
                    continue
                sharpe = np.mean(rets) / (np.std(rets) + 1e-8) * np.sqrt(252)
                if sharpe > best_sharpe:
                    best_sharpe = sharpe
                    best_params = (round(z_e, 2), round(z_x, 2))

        return best_params

    def _simulate_trades(self, spread: np.ndarray, z_e: float,
                          z_x: float) -> np.ndarray:
        """Simulate trades with given thresholds, return daily returns."""
        returns = []
        in_trade = 0  # 0=flat, 1=long_spread, -1=short_spread
        entry_price = 0.0

        for i in range(20, len(spread)):
            window = spread[i - 20:i + 1]
            mean = np.mean(window)
            std = np.std(window)
            if std <= 0:
                continue
            z = (window[-1] - mean) / std

            if in_trade == 0:
                if z < -z_e:
                    in_trade = 1
                    entry_price = spread[i]
                elif z > z_e:
                    in_trade = -1
                    entry_price = spread[i]
            elif abs(z) < z_x and in_trade != 0:
                pnl = in_trade * (spread[i] - entry_price)
                returns.append(pnl / (abs(entry_price) + 1e-8))
                in_trade = 0

        return np.array(returns)


# ═══════════════════ Hurst Exponent (mean-reversion indicator) ═══════════════

def hurst_exponent(ts: np.ndarray, max_lag: int = 20) -> float:
    """
    Hurst exponent: H > 0.5 = trending, H < 0.5 = mean-reverting, H = 0.5 = random walk.
    """
    ts = np.asarray(ts)
    n = len(ts)
    if n < 100:
        return 0.5

    lags = range(2, min(max_lag, n // 4))
    tau = [np.std(np.subtract(ts[lag:], ts[:-lag])) for lag in lags]

    # log-log regression: log(tau) = H * log(lag) + c
    poly = np.polyfit(np.log(lags), np.log(tau), 1)
    return float(poly[0])


def half_life_from_hurst(h: float, n_days: int = 252) -> float:
    """Approximate half-life from Hurst exponent."""
    if h >= 0.5:
        return 999.0
    # Rough approximation: more mean-reverting (lower H) → shorter half-life
    return max(1, (0.5 - h) * n_days * 2)
