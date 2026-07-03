"""合成 schema v3 report.json 供 serve 测试用 (不依赖真实录制)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _base_report(name: str, schema: int) -> dict[str, Any]:
    return {
        "schema_version": schema,
        "recording": name,
        "dock_sn": "DOCK_SN",
        "drone_sn": "DRONE_SN",
        "started_at_ms": 1_000_000,
        "ended_at_ms": 1_000_000 + 300_000,
        "duration_ms": 300_000,
        "total_envelopes": 0,
        "envelope_counts_by_topic_key": {},
        "phase_transitions": [],
        "verdicts": [],
        "alert_decisions": [],
        "metrics": {
            "peak_wind_gust_30s": 8.3,
            "peak_wind_gust_30s_at_ms": 1_000_000,
            "min_battery_percent": 41,
            "min_battery_percent_at_ms": 1_000_000,
            "longest_offline_ms": 0,
            "flight_duration_ms": 300_000,
            "total_verdicts": 0,
            "total_dispatched": 0,
            "total_suppressed": 0,
            "verdicts_by_code": {},
            "wind_direction_seconds": {},
        },
        "battery_samples": [
            {"rel_ms": 0, "percent": 100, "height_m": 0.0, "wind_ms": 2.0,
             "wind_direction": 1, "horizontal_speed_ms": 0.0,
             "vertical_speed_ms": 0.0},
            {"rel_ms": 10_000, "percent": 98, "height_m": 12.0, "wind_ms": 4.5,
             "wind_direction": 3, "horizontal_speed_ms": 6.2,
             "vertical_speed_ms": 1.5},
        ],
    }


def write_sample_report(
    root: Path, name: str, *, schema: int = 3,
    flight_samples: list[dict[str, Any]] | None = None,
    hsi_samples: list[dict[str, Any]] | None = None,
    **overrides: Any,
) -> None:
    d = _base_report(name, schema)
    if flight_samples is not None:
        d["flight_samples"] = flight_samples
    if hsi_samples is not None:
        d["hsi_samples"] = hsi_samples
    d.update(overrides)
    out = root / name / "dock_guard_report"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(
        json.dumps(d, ensure_ascii=False), encoding="utf-8"
    )
