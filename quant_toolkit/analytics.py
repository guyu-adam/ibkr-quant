"""
Performance analytics — based on quantstats.

- full_report: generates an HTML tear-sheet
- key_metrics: returns a compact dict of the most important numbers
"""

import io
import numpy as np
import pandas as pd
import quantstats as qs


def full_report(returns: pd.Series, output_file: str = "reports/quantstats_report.html",
                benchmark: str = "SPY") -> str:
    """Generate an HTML performance report.

    Args:
        returns:     daily or monthly strategy return series (index = date).
        output_file: path to write the HTML file.
        benchmark:   ticker to download as benchmark for comparison.

    Returns:
        The file path of the generated report.
    """
    import os
    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    qs.reports.html(returns, benchmark=benchmark, output=output_file)
    return output_file


def key_metrics(returns: pd.Series) -> dict:
    """Return a compact dictionary of key performance metrics.

    Returns keys: sharpe, sortino, max_dd, calmar, win_rate
    """
    returns = returns.dropna().astype(float)
    monthly = returns.resample("ME").apply(lambda x: (1 + x).prod() - 1)

    return {
        "sharpe":   round(qs.stats.sharpe(returns), 3),
        "sortino":  round(qs.stats.sortino(returns), 3),
        "max_dd":   round(qs.stats.max_drawdown(returns), 4),
        "calmar":   round(qs.stats.calmar(returns), 3),
        "win_rate": round((monthly > 0).mean(), 3),
    }
