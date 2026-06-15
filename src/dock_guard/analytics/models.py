"""Stage 4-E: 飞行复盘报告数据模型 (设计 §5)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

# v1 = Stage 3-D B3 baseline schema (无 metrics); v2 = 含 metrics 的完整 FlightReport.
# tests/replay/_helpers.py 仍返 v1 (薄壳裁掉 metrics).
SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class FlightMetrics:
    peak_wind_gust_30s: float | None
    peak_wind_gust_30s_at_ms: int | None
    min_battery_percent: int | None
    min_battery_percent_at_ms: int | None
    longest_offline_ms: int
    flight_duration_ms: int
    total_verdicts: int
    total_dispatched: int
    total_suppressed: int
    verdicts_by_code: dict[str, int]


@dataclass(frozen=True, slots=True)
class FlightReport:
    schema_version: int
    recording: str
    dock_sn: str
    drone_sn: str | None
    started_at_ms: int
    ended_at_ms: int
    duration_ms: int
    total_envelopes: int
    envelope_counts_by_topic_key: Mapping[str, int]
    phase_transitions: list[Mapping[str, Any]]
    verdicts: list[Mapping[str, Any]]
    alert_decisions: list[Mapping[str, Any]]
    metrics: FlightMetrics

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "recording": self.recording,
            "dock_sn": self.dock_sn,
            "drone_sn": self.drone_sn,
            "started_at_ms": self.started_at_ms,
            "ended_at_ms": self.ended_at_ms,
            "duration_ms": self.duration_ms,
            "total_envelopes": self.total_envelopes,
            "envelope_counts_by_topic_key": dict(self.envelope_counts_by_topic_key),
            "phase_transitions": [dict(t) for t in self.phase_transitions],
            "verdicts": [dict(v) for v in self.verdicts],
            "alert_decisions": [dict(d) for d in self.alert_decisions],
            "metrics": asdict(self.metrics),
        }
