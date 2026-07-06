"""Stage 4-E: 飞行复盘报告数据模型 (设计 §5)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

# v1 = Stage 3-D B3 baseline schema (无 metrics)
# v2 = Stage 4-E + metrics (5 个指标)
# v3 = Stage 5-F + battery_samples 时序 (向后纯字段添加, 老 v2 reader 仍可读忽略字段)
# tests/replay/_helpers.py 仍返 v1 (薄壳裁掉 metrics + battery_samples).
# v4 = Stage 6 + flight_samples 原频 (OSD ~0.5Hz) 采样 (纯添加, 老 reader 忽略).
# v5 = Stage 6 Phase2 + hsi_samples (drc/up hsi_info_push 下视距离; 纯添加).
# v6 = 海测 VPS 展示 + stick_samples (drc/down stick_control 控制输入; 纯添加).
# (v6 内纯添加) FlightSample 加 latitude/longitude (drone OSD 直读; 不升 schema, 水平漂移).
# v7 = 海测 VPS 展示 + link_samples (drc/up drc_geo_connect_info_push 链路质量; 纯添加).
SCHEMA_VERSION = 7


@dataclass(frozen=True, slots=True)
class BatterySample:
    """每 10s 一次的电池快照 (Stage 5-F 设计 §5.1)."""

    rel_ms: int           # 距 started_at_ms 的相对毫秒
    percent: int          # battery_capacity_percent (0-100)
    height_m: float       # drone height (m)
    wind_ms: float        # wind_gust_max_30s (m/s)
    # wind_direction enum_int (1=N..8=NW), None 表示该采样时刻未上报
    # 纯添加字段, schema_version 保持 3 (向前兼容).
    wind_direction: int | None = None
    # 飞行器速度时序 (m/s). None = 该采样时刻未上报.
    # 纯添加字段, schema_version 保持 3 (向后兼容, 同 wind_direction).
    horizontal_speed_ms: float | None = None   # OSD horizontal_speed (>=0)
    vertical_speed_ms: float | None = None       # OSD vertical_speed (负=下降)


@dataclass(frozen=True, slots=True)
class FlightSample:
    """原频 (OSD ~0.5Hz) 飞行采样 (安全视图 §4.1). 除 rel_ms 全 nullable."""

    rel_ms: int
    height_m: float | None = None
    vertical_speed_ms: float | None = None
    horizontal_speed_ms: float | None = None
    attitude_head: float | None = None
    attitude_pitch: float | None = None
    attitude_roll: float | None = None
    gps_number: int | None = None
    rtk_number: int | None = None
    is_fixed: bool | None = None
    drc_state: str | None = None
    latitude: float | None = None       # WGS84 小数度, 原始值 (安全视图水平漂移)
    longitude: float | None = None


@dataclass(frozen=True, slots=True)
class HsiSample:
    """drc/up hsi_info_push 下视距离采样 (~1Hz). 除 rel_ms 全 nullable."""

    rel_ms: int
    down_distance_mm: int | None = None       # 原始 mm; >=60000 无效(NA)
    down_enable: bool | None = None
    down_work: bool | None = None
    up_distance_mm: int | None = None
    up_enable: bool | None = None
    up_work: bool | None = None
    around_distances_mm: list[int] | None = None
    elevation_m: float | None = None          # 该时刻 facts.elevation 快照 (相对起飞点)


@dataclass(frozen=True, slots=True)
class StickSample:
    # drc/down stick_control 控制输入; 原始 364~1684, 1024=回中; 事件驱动, 缺字段 None.
    rel_ms: int            # 距 started_at_ms 的相对毫秒
    roll: int | None = None
    pitch: int | None = None
    yaw: int | None = None
    throttle: int | None = None


@dataclass(frozen=True, slots=True)
class LinkSample:
    # drc/up drc_geo_connect_info_push 链路质量; 事件驱动, 缺字段 None.
    rel_ms: int
    sdr_quality: int | None = None      # 图传链路质量 0-5
    fourg_quality: int | None = None    # 4G 链路质量 0-5 (JSON 键 "4g_quality")


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
    # 风向计数 (key='1'..'8' 对应 N/NE/E/SE/S/SW/W/NW; value=秒数)
    # 纯添加字段, schema_version 保持 3 (向前兼容).
    wind_direction_seconds: dict[str, int] = field(default_factory=dict)


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
    battery_samples: list[BatterySample]    # NEW v3 (Stage 5-F)
    flight_samples: list[FlightSample] = field(default_factory=list)  # NEW v4
    hsi_samples: list[HsiSample] = field(default_factory=list)        # NEW v5
    stick_samples: list[StickSample] = field(default_factory=list)   # NEW v6
    link_samples: list[LinkSample] = field(default_factory=list)     # NEW v7
    transfer_events: list[dict] = field(default_factory=list)        # NEW (pure-add, 不升 schema)
    hms_events: list[dict] = field(default_factory=list)             # NEW (pure-add, 不升 schema)

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
            "battery_samples": [asdict(s) for s in self.battery_samples],
            "flight_samples": [asdict(s) for s in self.flight_samples],
            "hsi_samples": [asdict(s) for s in self.hsi_samples],
            "stick_samples": [asdict(s) for s in self.stick_samples],
            "link_samples": [asdict(s) for s in self.link_samples],
            "transfer_events": [dict(e) for e in self.transfer_events],
            "hms_events": [dict(e) for e in self.hms_events],
        }
