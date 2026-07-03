from dataclasses import asdict

from dock_guard.analytics.models import (
    SCHEMA_VERSION,
    FlightMetrics,
    FlightReport,
    StickSample,
)


def _bare_report(**kw):
    metrics = FlightMetrics(
        peak_wind_gust_30s=None, peak_wind_gust_30s_at_ms=None,
        min_battery_percent=None, min_battery_percent_at_ms=None,
        longest_offline_ms=0, flight_duration_ms=0,
        total_verdicts=0, total_dispatched=0, total_suppressed=0,
        verdicts_by_code={},
    )
    base = dict(
        schema_version=SCHEMA_VERSION, recording="x", dock_sn="D", drone_sn=None,
        started_at_ms=0, ended_at_ms=0, duration_ms=0, total_envelopes=0,
        envelope_counts_by_topic_key={}, phase_transitions=[], verdicts=[],
        alert_decisions=[], metrics=metrics, battery_samples=[],
    )
    base.update(kw)
    return FlightReport(**base)


def test_schema_version_is_6():
    assert SCHEMA_VERSION == 6


def test_stick_sample_roundtrip():
    s = StickSample(rel_ms=1200, roll=1354, pitch=1024, yaw=364, throttle=1024)
    assert asdict(s) == {
        "rel_ms": 1200, "roll": 1354, "pitch": 1024, "yaw": 364, "throttle": 1024,
    }


def test_stick_sample_missing_axis_is_none():
    s = StickSample(rel_ms=0, roll=None, pitch=1024, yaw=None, throttle=None)
    assert s.roll is None and s.yaw is None and s.throttle is None


def test_report_to_dict_includes_stick_samples():
    rep = _bare_report(stick_samples=[
        StickSample(rel_ms=5, roll=1024, pitch=1024, yaw=1024, throttle=1024),
    ])
    d = rep.to_dict()
    assert d["schema_version"] == 6
    assert d["stick_samples"] == [
        {"rel_ms": 5, "roll": 1024, "pitch": 1024, "yaw": 1024, "throttle": 1024},
    ]


def test_report_stick_samples_defaults_empty():
    rep = _bare_report()
    assert rep.stick_samples == []
    assert rep.to_dict()["stick_samples"] == []
