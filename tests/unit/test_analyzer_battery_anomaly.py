"""Stage 5-F Task 5: 异常检测单测.

谁运行: pytest discover. 同义文件: 无. 数据: 合成 BatteryReference + samples.
用户指令: "依次接着做, 做完记得提交, 不用每个都停".
"""

from __future__ import annotations

from dock_guard.analytics.analyzers.battery_anomaly import (
    SampleFlag,
    evaluate_flight,
)
from dock_guard.analytics.analyzers.battery_models import (
    BatteryReference,
    BucketStats,
    FlightAnomalyResult,
)
from dock_guard.analytics.models import BatterySample


def _normal_ref() -> BatteryReference:
    """合成: 所有 18 桶 mean=0.05 p95=0.10 p99=0.15."""
    buckets = {}
    for w in ("w0_3", "w3_6", "w6_inf"):
        for h in ("h_lt50", "h_ge50"):
            for s in ("soc_high", "soc_mid", "soc_low"):
                buckets[f"{w}.{h}.{s}"] = BucketStats(
                    sample_count=100, mean=0.05, p50=0.05,
                    p95=0.10, p99=0.15, max=0.20,
                    residual_std=0.02, r_squared=0.7, status=None,
                )
    return BatteryReference(buckets=buckets)


def _samples(rate_per_sec: float, n: int = 10) -> list[BatterySample]:
    """n 个 100s 间隔样本, 耗电 rate_per_sec %/s.

    用 100s 间隔避免 int percent 截断 -> 0.12 %/s 真能产 0.12 而非 0.2.
    """
    out = []
    pct = 90
    for i in range(n):
        out.append(BatterySample(
            rel_ms=i * 100_000, percent=pct,
            height_m=30, wind_ms=2,
        ))
        pct = max(0, int(pct - rate_per_sec * 100))
    return out


class TestEvaluate:
    def test_green_flight_not_anomaly(self) -> None:
        """速率慢于 p95=0.10 -> 全 green."""
        res = evaluate_flight(_samples(0.04), _normal_ref())
        assert res.red_count == 0
        assert not res.is_anomaly

    def test_red_above_p99_is_anomaly(self) -> None:
        """速率 > p99=0.15 -> 多个 red -> 异常."""
        res = evaluate_flight(_samples(0.25), _normal_ref())
        assert res.red_count >= 3
        assert res.is_anomaly

    def test_yellow_between_p95_p99(self) -> None:
        """速率 0.12 ∈ (0.10=p95, 0.15=p99) -> yellow."""
        res = evaluate_flight(_samples(0.12), _normal_ref())
        assert res.yellow_count > 0

    def test_no_reference_for_unknown_bucket(self) -> None:
        """空 reference -> 全 NO_REFERENCE, 不算 red."""
        res = evaluate_flight(_samples(0.25), BatteryReference(buckets={}))
        assert all(f == SampleFlag.NO_REFERENCE.value for f in res.flags)
        assert res.red_count == 0

    def test_anomaly_result_constructor(self) -> None:
        """直接构造 FlightAnomalyResult 字段完整 (dataclass 完整性)."""
        res = FlightAnomalyResult(
            recording="x", dock_sn="D", drone_sn=None,
            sample_count=5, red_count=2, yellow_count=1,
            is_anomaly=False, flags=[],
        )
        # red_count < 3 -> not anomaly
        assert not res.is_anomaly
