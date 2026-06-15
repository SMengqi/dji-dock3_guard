"""Stage 5-F: 异常检测 (设计 §8).

evaluate_flight: 单架次速率 vs reference 桶的 p95/p99 比对.
SampleFlag: GREEN / YELLOW / RED / NO_REFERENCE.
ANOMALY_RED_THRESHOLD = 3 (架次内 red ≥ 3 -> is_anomaly=True).
"""

from __future__ import annotations

from enum import StrEnum

from dock_guard.analytics.analyzers.battery_buckets import (
    bucket_key_for,
    compute_discharge_rates,
    smooth_30s,
)
from dock_guard.analytics.analyzers.battery_models import (
    BatteryReference,
    FlightAnomalyResult,
)
from dock_guard.analytics.models import BatterySample


class SampleFlag(StrEnum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"
    NO_REFERENCE = "NO_REFERENCE"


ANOMALY_RED_THRESHOLD = 3


def evaluate_flight(
    samples: list[BatterySample], ref: BatteryReference,
    *, recording: str = "?", dock_sn: str = "?",
    drone_sn: str | None = None,
) -> FlightAnomalyResult:
    """计算每架次异常评分 (设计 §8.1).

    smoothed[i] 对应 samples[i+1] 的速率 (差分),
    若 i+1 越界则用 samples[i] 兜底.
    """
    rates = compute_discharge_rates(samples)
    smoothed = smooth_30s(rates)
    flags: list[SampleFlag] = []
    for i, rate in enumerate(smoothed):
        s = samples[i + 1] if i + 1 < len(samples) else samples[i]
        key = bucket_key_for(s.wind_ms, s.height_m, s.percent)
        stats = ref.buckets.get(key)
        if stats is None or stats.status == "insufficient_data":
            flags.append(SampleFlag.NO_REFERENCE)
            continue
        if rate > stats.p99:
            flags.append(SampleFlag.RED)
        elif rate > stats.p95:
            flags.append(SampleFlag.YELLOW)
        else:
            flags.append(SampleFlag.GREEN)
    red_count = sum(1 for f in flags if f == SampleFlag.RED)
    yellow_count = sum(1 for f in flags if f == SampleFlag.YELLOW)
    return FlightAnomalyResult(
        recording=recording, dock_sn=dock_sn, drone_sn=drone_sn,
        sample_count=len(flags),
        red_count=red_count, yellow_count=yellow_count,
        is_anomaly=red_count >= ANOMALY_RED_THRESHOLD,
        flags=[f.value for f in flags],
    )
