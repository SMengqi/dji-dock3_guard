"""Stage 5-F: 桶内统计 + OLS R^2 (设计 §7.2-§7.3).

compute_bucket_stats: rates list -> {sample_count, discharge_rate_pct_per_sec,
                                      fit_quality} dict; < min_samples 返 None
ols_r_squared: (x, y) numpy 数组 -> R^2 in [0, 1]
"""

from __future__ import annotations

from typing import Any

import numpy as np


def compute_bucket_stats(
    rates: list[float], *, min_samples: int = 30,
) -> dict[str, Any] | None:
    """桶内速率统计. < min_samples -> None (调用方标 insufficient_data)."""
    if len(rates) < min_samples:
        return None
    arr = np.array(rates, dtype=float)
    return {
        "sample_count": len(rates),
        "discharge_rate_pct_per_sec": {
            "mean": float(arr.mean()),
            "p50":  float(np.percentile(arr, 50)),
            "p95":  float(np.percentile(arr, 95)),
            "p99":  float(np.percentile(arr, 99)),
            "max":  float(arr.max()),
        },
        "fit_quality": {
            "residual_std": float(arr.std()),
            "r_squared": ols_r_squared(np.arange(len(arr), dtype=float), arr),
        },
    }


def ols_r_squared(x: np.ndarray, y: np.ndarray) -> float:
    """简单线性 OLS, 返 R^2 in [0, 1] (设计 §7.3).

    < 2 个点 -> 0.0 (无法拟合).
    ss_tot = 0 (y 全相同) -> 0.0 (退化情况).
    """
    if len(x) < 2:
        return 0.0
    slope, intercept = np.polyfit(x, y, 1)
    y_pred = slope * x + intercept
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
