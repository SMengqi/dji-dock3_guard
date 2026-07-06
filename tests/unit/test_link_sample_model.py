from dataclasses import asdict

from dock_guard.analytics.models import (
    SCHEMA_VERSION,
    FlightMetrics,
    FlightReport,
    LinkSample,
)


def _bare_report(**kw):
    metrics = FlightMetrics(
        peak_wind_gust_30s=None, peak_wind_gust_30s_at_ms=None,
        min_battery_percent=None, min_battery_percent_at_ms=None,
        longest_offline_ms=0, flight_duration_ms=0,
        total_verdicts=0, total_dispatched=0, total_suppressed=0,
        verdicts_by_code={}, wind_direction_seconds={},
    )
    base = dict(
        schema_version=SCHEMA_VERSION, recording="x", dock_sn="D", drone_sn=None,
        started_at_ms=0, ended_at_ms=0, duration_ms=0, total_envelopes=0,
        envelope_counts_by_topic_key={}, phase_transitions=[], verdicts=[],
        alert_decisions=[], metrics=metrics, battery_samples=[],
    )
    base.update(kw)
    return FlightReport(**base)


def test_schema_version_is_7():
    assert SCHEMA_VERSION == 7


def test_link_sample_roundtrip():
    s = LinkSample(rel_ms=500, sdr_quality=5, fourg_quality=0)
    assert asdict(s) == {"rel_ms": 500, "sdr_quality": 5, "fourg_quality": 0}


def test_link_sample_missing_none():
    s = LinkSample(rel_ms=0)
    assert s.sdr_quality is None and s.fourg_quality is None


def test_report_to_dict_includes_link_samples():
    rep = _bare_report(link_samples=[LinkSample(rel_ms=5, sdr_quality=3, fourg_quality=2)])
    d = rep.to_dict()
    assert d["schema_version"] == 7
    assert d["link_samples"] == [{"rel_ms": 5, "sdr_quality": 3, "fourg_quality": 2}]


def test_report_link_samples_defaults_empty():
    assert _bare_report().link_samples == []
