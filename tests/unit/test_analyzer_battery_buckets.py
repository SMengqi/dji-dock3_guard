"""Stage 5-F Task 3: battery_buckets 分桶 + 速率 + 30s 滑窗单测.

谁运行: pytest discover. 同义文件: 无. 数据: 纯合成 BatterySample.
用户指令: "commit T2 然后开 T3".
"""

from __future__ import annotations

import pytest

from dock_guard.analytics.analyzers.battery_buckets import (
    bucket_key_for,
    compute_discharge_rates,
    group_rates_by_bucket,
    smooth_30s,
)
from dock_guard.analytics.models import BatterySample


class TestBucketKey:
    @pytest.mark.parametrize("wind,height,pct,expected", [
        (1.0, 30, 75, "w0_3.h_lt50.soc_high"),
        (5.0, 60, 50, "w3_6.h_ge50.soc_mid"),
        (7.0, 30, 20, "w6_inf.h_lt50.soc_low"),
        (0.5, 80, 95, "w0_3.h_ge50.soc_high"),
        # 边界 (3 m/s, 50m, 60%): wind 3.0 < 3.0 假 -> w3_6;
        # height 50 < 50 假 -> h_ge50; percent 60 < 60 假 -> soc_high.
        # 三个边界都用严格小于, 边界值统一归到上一级桶.
        (3.0, 50, 60, "w3_6.h_ge50.soc_high"),
    ])
    def test_bucket_key_for(
        self, wind: float, height: float, pct: int, expected: str
    ) -> None:
        assert bucket_key_for(wind, height, pct) == expected


class TestDischargeRates:
    def test_simple_1pct_per_sec(self) -> None:
        """100% -> 90% in 10s = 1.0 %/s."""
        samples = [
            BatterySample(rel_ms=0,      percent=100, height_m=10, wind_ms=2),
            BatterySample(rel_ms=10_000, percent=90,  height_m=10, wind_ms=2),
        ]
        rates = compute_discharge_rates(samples)
        assert len(rates) == 1
        assert rates[0] == pytest.approx(1.0, abs=0.01)

    def test_zero_dt_safe(self) -> None:
        """连续 2 样本 rel_ms 相同 -> 不抛 ZeroDivisionError."""
        samples = [
            BatterySample(rel_ms=0, percent=100, height_m=10, wind_ms=2),
            BatterySample(rel_ms=0, percent=99,  height_m=10, wind_ms=2),
        ]
        rates = compute_discharge_rates(samples)
        assert len(rates) == 1   # 不抛, 返 0.0


class TestSmooth:
    def test_smooth_30s_3sample_window(self) -> None:
        """中间 index 取相邻 3 样本均值."""
        rates = [1.0, 1.5, 2.0, 1.5, 1.0]
        s = smooth_30s(rates)
        assert len(s) == len(rates)
        # index 2 = (1.5 + 2.0 + 1.5) / 3 = 1.6667
        assert s[2] == pytest.approx(1.6667, abs=0.01)
        # 边界 (index 0 / 末尾) 保留原值
        assert s[0] == rates[0]
        assert s[-1] == rates[-1]

    def test_smooth_too_short_returns_copy(self) -> None:
        """< 3 样本 -> 原样返."""
        assert smooth_30s([]) == []
        assert smooth_30s([1.0, 2.0]) == [1.0, 2.0]


class TestGroupByBucket:
    def test_group_distributes_by_bucket(self) -> None:
        samples = [
            BatterySample(rel_ms=10_000, percent=78, height_m=30, wind_ms=2),
            BatterySample(rel_ms=20_000, percent=76, height_m=30, wind_ms=2),
            BatterySample(rel_ms=30_000, percent=50, height_m=60, wind_ms=5),
        ]
        rates = [0.2, 0.2, 2.6]   # 假设速率 (匹配 samples 同长度)
        groups = group_rates_by_bucket(samples, rates)
        assert "w0_3.h_lt50.soc_high" in groups
        assert "w3_6.h_ge50.soc_mid" in groups
        # 前 2 个 sample -> w0_3.h_lt50.soc_high
        assert len(groups["w0_3.h_lt50.soc_high"]) == 2

    def test_group_skips_non_positive_rates(self) -> None:
        """充电 / 零速率 (rate <= 0) 应跳过."""
        samples = [
            BatterySample(rel_ms=0,      percent=80, height_m=30, wind_ms=2),
            BatterySample(rel_ms=10_000, percent=80, height_m=30, wind_ms=2),
        ]
        rates = [0.0, -1.0]   # 零 + 负 (充电)
        groups = group_rates_by_bucket(samples, rates)
        assert groups == {}
