"""Stage 5-F: 桶 / reference / 异常结果 dataclass (设计 §6 + §8)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BucketStats:
    """单桶速率统计 + 拟合质量. status='insufficient_data' 时其他字段无意义."""

    sample_count: int
    mean: float
    p50: float
    p95: float
    p99: float
    max: float
    residual_std: float
    r_squared: float
    status: str | None = None    # "insufficient_data" or None


@dataclass(frozen=True, slots=True)
class BatteryReference:
    """跨架次电池基线 (设计 §6 schema)."""

    buckets: dict[str, BucketStats]
    generated_at_ms: int = 0
    recording_count: int = 0
    total_sample_count: int = 0


@dataclass(frozen=True, slots=True)
class FlightAnomalyResult:
    """单架次异常评分结果 (设计 §8.1)."""

    recording: str
    dock_sn: str
    drone_sn: str | None
    sample_count: int
    red_count: int
    yellow_count: int
    is_anomaly: bool
    flags: list[str]    # SampleFlag.value 序列
