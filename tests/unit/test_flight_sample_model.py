"""schema v4: FlightSample + FlightReport.flight_samples 往返."""

from __future__ import annotations

import json

from dock_guard.analytics.__main__ import _from_dict
from dock_guard.analytics.models import (
    SCHEMA_VERSION,
    FlightMetrics,
    FlightReport,
    FlightSample,
)


def _metrics() -> FlightMetrics:
    return FlightMetrics(
        peak_wind_gust_30s=None, peak_wind_gust_30s_at_ms=None,
        min_battery_percent=None, min_battery_percent_at_ms=None,
        longest_offline_ms=0, flight_duration_ms=0,
        total_verdicts=0, total_dispatched=0, total_suppressed=0,
        verdicts_by_code={},
    )


def _report(flight_samples: list[FlightSample]) -> FlightReport:
    return FlightReport(
        schema_version=SCHEMA_VERSION, recording="rec", dock_sn="D", drone_sn="A",
        started_at_ms=0, ended_at_ms=1000, duration_ms=1000, total_envelopes=0,
        envelope_counts_by_topic_key={}, phase_transitions=[], verdicts=[],
        alert_decisions=[], metrics=_metrics(), battery_samples=[],
        flight_samples=flight_samples,
    )


def test_schema_version_is_4() -> None:
    assert SCHEMA_VERSION == 4


def test_to_dict_includes_flight_samples() -> None:
    rep = _report([FlightSample(
        rel_ms=0, height_m=1.5, vertical_speed_ms=-0.5, horizontal_speed_ms=3.0,
        attitude_head=90.0, attitude_pitch=2.0, attitude_roll=-1.0,
        gps_number=12, rtk_number=20, is_fixed=True, drc_state="connected",
    )])
    d = rep.to_dict()
    assert d["schema_version"] == 4
    s0 = d["flight_samples"][0]
    assert s0["is_fixed"] is True and s0["drc_state"] == "connected"
    assert s0["gps_number"] == 12
    json.dumps(d)  # JSON safe


def test_from_dict_v4_roundtrip() -> None:
    rep = _report([FlightSample(rel_ms=10, height_m=2.0, drc_state="x")])
    rep2 = _from_dict(rep.to_dict())
    assert rep2.schema_version == 4
    assert rep2.flight_samples[0].drc_state == "x"
    assert rep2.flight_samples[0].height_m == 2.0


def test_from_dict_v3_defaults_empty_flight_samples() -> None:
    d = _report([]).to_dict()
    d["schema_version"] = 3
    d.pop("flight_samples")
    rep = _from_dict(d)
    assert rep.flight_samples == []


def test_default_flight_samples_empty() -> None:
    # 现有构造点不传 flight_samples 仍可用 (默认空)
    rep = FlightReport(
        schema_version=4, recording="r", dock_sn="D", drone_sn=None,
        started_at_ms=0, ended_at_ms=0, duration_ms=0, total_envelopes=0,
        envelope_counts_by_topic_key={}, phase_transitions=[], verdicts=[],
        alert_decisions=[], metrics=_metrics(), battery_samples=[],
    )
    assert rep.flight_samples == []
