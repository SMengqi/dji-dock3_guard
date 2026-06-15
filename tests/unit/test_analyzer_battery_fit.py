"""Stage 5-F Task 4: 桶内统计 + OLS R^2 单测.

谁运行: pytest discover. 同义文件: 无.
数据: 合成 numpy 数组 (线性/噪声) + Python rate list.
用户指令: "commit T3 然后开 T4".
"""

from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")

from dock_guard.analytics.analyzers.battery_fit import (  # noqa: E402
    compute_bucket_stats,
    ols_r_squared,
)


class TestComputeBucketStats:
    def test_below_min_samples_returns_none(self) -> None:
        rates = [0.1] * 20
        assert compute_bucket_stats(rates, min_samples=30) is None

    def test_populated_bucket_stats(self) -> None:
        """100 个 0.05..0.149 等差; mean ≈ 0.0995."""
        rates = [0.05 + i * 0.001 for i in range(100)]
        stats = compute_bucket_stats(rates, min_samples=30)
        assert stats is not None
        assert stats["sample_count"] == 100
        d = stats["discharge_rate_pct_per_sec"]
        assert d["mean"] == pytest.approx(0.0995, abs=0.005)
        assert d["p95"] > d["p50"]
        assert d["p99"] > d["p95"]
        assert d["max"] == pytest.approx(0.149, abs=0.005)


class TestOlsRSquared:
    def test_perfect_linear_r2_1(self) -> None:
        x = np.arange(100, dtype=float)
        y = 2.0 * x + 5.0
        assert ols_r_squared(x, y) == pytest.approx(1.0, abs=1e-6)

    def test_random_noise_low_r2(self) -> None:
        rng = np.random.default_rng(42)
        x = np.arange(100, dtype=float)
        y = rng.standard_normal(100)
        assert ols_r_squared(x, y) < 0.1
