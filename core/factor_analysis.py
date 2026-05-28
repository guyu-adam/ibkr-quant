"""
因子分析框架 — IC 衰减 / 因子拥挤度 / 行业中性化 / 换手率分析。

Usage:
    from core.factor_analysis import FactorAnalyzer
    fa = FactorAnalyzer(factors_df, forward_returns)
    print(fa.ic_summary())       # 各因子 IC/IR
    print(fa.ic_decay())         # IC 衰减曲线
    print(fa.crowding_score())   # 因子拥挤度
"""

import numpy as np
import pandas as pd
import logging

log = logging.getLogger(__name__)


class FactorAnalyzer:
    """Comprehensive factor evaluation toolkit."""

    def __init__(self, factors: pd.DataFrame, forward_returns: pd.Series,
                 group_labels: pd.Series | None = None):
        """
        Args:
            factors: T×N DataFrame of factor values (rows=dates, cols=assets)
            forward_returns: T Series of N-period forward returns of a market index or cross-section
            group_labels: optional industry/sector labels for neutralization
        """
        self.factors = factors
        self.fwd_returns = forward_returns
        self.groups = group_labels

    # ── IC Analysis ──────────────────────────────────────────────────────
    def ic_summary(self) -> pd.DataFrame:
        """Rank IC per factor with IR (IC mean / IC std)."""
        results = []
        common = self.factors.index.intersection(self.fwd_returns.dropna().index)
        for col in self.factors.columns:
            f = self.factors[col].loc[common]
            r = self.fwd_returns.loc[common]
            valid = ~(f.isna() | r.isna())
            if valid.sum() < 30:
                results.append({"factor": col, "IC_mean": 0, "IC_std": 0,
                               "IR": 0, "abs_IC_mean": 0, "n_obs": valid.sum()})
                continue

            ic_series = f[valid].corr(r[valid], method="spearman")
            # Rolling IC for IR
            rolling_ic = []
            window_size = min(60, len(f[valid]) // 4)
            for i in range(window_size, len(f[valid])):
                f_sub = f[valid].iloc[i - window_size:i]
                r_sub = r[valid].iloc[i - window_size:i]
                ic = f_sub.corr(r_sub, method="spearman")
                rolling_ic.append(ic)
            ic_arr = np.array(rolling_ic)
            ic_mean = float(np.mean(ic_arr)) if len(ic_arr) > 0 else float(ic_series)
            ic_std = float(np.std(ic_arr)) if len(ic_arr) > 0 else 0.0
            ir = ic_mean / (ic_std + 1e-8)

            results.append({
                "factor": col, "IC_mean": round(ic_mean, 4),
                "IC_std": round(ic_std, 4), "IR": round(ir, 2),
                "abs_IC_mean": round(abs(ic_mean), 4),
                "n_obs": valid.sum(),
            })

        return pd.DataFrame(results).sort_values("abs_IC_mean", ascending=False)

    # ── IC Decay ─────────────────────────────────────────────────────────
    def ic_decay(self, max_horizon: int = 20) -> pd.DataFrame:
        """IC decay over horizons 1..max_horizon days."""
        common = self.factors.index.intersection(self.fwd_returns.dropna().index)
        decays = {}

        for col in self.factors.columns[:10]:  # Top 10 for speed
            ic_horizons = []
            for h in range(1, max_horizon + 1):
                f = self.factors[col].loc[common]
                # Shift factor back to align with future return at horizon h
                f_aligned = f.iloc[:-h] if h > 0 else f
                r = self.fwd_returns.loc[common].iloc[h:]
                valid = ~(f_aligned.isna() | r.isna())
                if valid.sum() > 30:
                    ic = f_aligned[valid].corr(r[valid], method="spearman")
                    ic_horizons.append(round(ic, 4))
                else:
                    ic_horizons.append(0.0)
            decays[col] = ic_horizons

        return pd.DataFrame(decays, index=range(1, max_horizon + 1))

    def half_life(self) -> dict[str, int]:
        """Estimate IC half-life for each factor (days until IC drops to 50% of peak)."""
        decay_df = self.ic_decay()
        hl = {}
        for col in decay_df.columns:
            peak = abs(decay_df[col].iloc[0])
            if peak <= 0:
                hl[col] = 0
                continue
            for h in range(len(decay_df)):
                if abs(decay_df[col].iloc[h]) < peak * 0.5:
                    hl[col] = h + 1
                    break
            else:
                hl[col] = len(decay_df)
        return hl

    # ── Factor Crowding ──────────────────────────────────────────────────
    def crowding_score(self, window: int = 60) -> pd.DataFrame:
        """
        Factor crowding metrics:
          - Pairwise correlation: higher corr among top factors → more crowded
          - Returns concentration: % of returns explained by top factor
          - Turnover concentration: % of volume in top-ranked stocks
        """
        common = self.factors.index.intersection(self.fwd_returns.dropna().index)
        n_factors = min(20, len(self.factors.columns))
        scores = []

        for i in range(window, len(common)):
            sub = self.factors.iloc[i - window:i][self.factors.columns[:n_factors]]
            # Average pairwise correlation of top factors
            corr = sub.corr(method="spearman").values
            # Upper triangle mean (ex diagonal)
            upper = corr[np.triu_indices_from(corr, k=1)]
            avg_corr = float(np.mean(np.abs(upper))) if len(upper) > 0 else 0.0
            scores.append({
                "date": common[i],
                "avg_corr": avg_corr,
                "crowded": avg_corr > 0.5,
            })

        return pd.DataFrame(scores).set_index("date")

    # ── Sector/Industry Neutralization ───────────────────────────────────
    def neutralize(self) -> pd.DataFrame:
        """Cross-sectional industry neutralization: factor - mean(factor | industry)."""
        if self.groups is None:
            log.warning("No industry labels provided — returning original factors")
            return self.factors

        neutralized = self.factors.copy()
        unique_groups = self.groups.dropna().unique()

        for date in neutralized.index:
            for group in unique_groups:
                mask = self.groups == group
                if mask.sum() <= 1:
                    continue
                common_cols = neutralized.columns.intersection(mask.index)
                if len(common_cols) == 0:
                    continue
                group_mean = neutralized.loc[date, common_cols].mean()
                neutralized.loc[date, common_cols] -= group_mean

        return neutralized

    # ── Turnover Analysis ────────────────────────────────────────────────
    def turnover(self, top_k: int = 20) -> pd.DataFrame:
        """
        Daily turnover of top-k rankings: what % of the top-k changed from yesterday?
        Lower turnover = more stable factor.
        """
        turnover_rates = []
        for i in range(1, len(self.factors)):
            prev_rank = self.factors.iloc[i - 1].nlargest(top_k).index
            curr_rank = self.factors.iloc[i].nlargest(top_k).index
            overlap = len(set(prev_rank) & set(curr_rank))
            turnover = 1 - overlap / top_k
            turnover_rates.append({
                "date": self.factors.index[i],
                "turnover": turnover,
            })

        return pd.DataFrame(turnover_rates).set_index("date")

    # ── Fama-MacBeth Regression ──────────────────────────────────────────
    def fama_macbeth(self) -> pd.DataFrame:
        """
        Two-pass Fama-MacBeth regression:
          Pass 1: cross-sectional regression of returns on factors each period
          Pass 2: time-series average of coefficients → risk premia + t-stats
        """
        common = self.factors.index.intersection(self.fwd_returns.dropna().index)
        factor_cols = self.factors.columns[:10]  # limit for speed

        ts_coefficients = []
        for t in common:
            r = self.fwd_returns.loc[t]
            X = self.factors.loc[t, factor_cols].fillna(0.0)
            valid = ~(r.isna() | X.isna().any(axis=1))
            if valid.sum() < 10:
                continue
            # Cross-sectional regression: r_i = alpha + beta * factor_i + eps
            X_mat = X[valid].values
            y_vec = r[valid].values
            try:
                coef = np.linalg.lstsq(
                    np.column_stack([np.ones(len(X_mat)), X_mat]),
                    y_vec, rcond=None
                )[0]
                ts_coefficients.append(coef)
            except np.linalg.LinAlgError:
                continue

        if not ts_coefficients:
            return pd.DataFrame()

        coef_arr = np.array(ts_coefficients)
        means = coef_arr.mean(axis=0)
        stds = coef_arr.std(axis=0)
        t_stats = means / (stds / np.sqrt(len(ts_coefficients)) + 1e-8)

        result = pd.DataFrame({
            "factor": ["alpha"] + list(factor_cols),
            "risk_premium": means,
            "std_error": stds / np.sqrt(len(ts_coefficients)),
            "t_stat": t_stats,
        })
        result["significant"] = abs(result["t_stat"]) > 2.0
        return result

    # ── Quick Report ─────────────────────────────────────────────────────
    def report(self) -> str:
        """One-page factor evaluation report."""
        ic = self.ic_summary()
        hl = self.half_life()
        lines = ["=" * 60, "  FACTOR EVALUATION REPORT", "=" * 60, ""]

        lines.append("── Top 10 Factors by |IC| ──")
        top10 = ic.head(10)
        for _, row in top10.iterrows():
            hl_val = hl.get(row["factor"], "?")
            lines.append(f"  {row['factor']:<20}  |IC|={row['abs_IC_mean']:.4f}  "
                        f"IR={row['IR']:.2f}  HL={hl_val}d")

        lines.append("")
        lines.append("── Crowding ──")
        crowd = self.crowding_score()
        if not crowd.empty:
            avg_corr = crowd["avg_corr"].mean()
            crowded_pct = crowd["crowded"].mean()
            lines.append(f"  Avg pairwise factor corr: {avg_corr:.3f}")
            lines.append(f"  % periods crowded: {crowded_pct:.1%}")

        lines.append("")
        lines.append("── Turnover ──")
        to = self.turnover()
        if not to.empty:
            lines.append(f"  Avg daily top-20 turnover: {to['turnover'].mean():.1%}")

        lines.append("=" * 60)
        return "\n".join(lines)
