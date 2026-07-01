"""单架次报告"## 水平/垂直速度曲线"段单测 (仿 test_report_wind_speed_chart)."""

from __future__ import annotations

import re

from dock_guard.analytics.models import (
    SCHEMA_VERSION,
    BatterySample,
    FlightMetrics,
    FlightReport,
)
from dock_guard.analytics.report import render_markdown


def _make_report(samples: list[BatterySample]) -> FlightReport:
    m = FlightMetrics(
        peak_wind_gust_30s=None, peak_wind_gust_30s_at_ms=None,
        min_battery_percent=None, min_battery_percent_at_ms=None,
        longest_offline_ms=0, flight_duration_ms=0,
        total_verdicts=0, total_dispatched=0, total_suppressed=0,
        verdicts_by_code={}, wind_direction_seconds={},
    )
    return FlightReport(
        schema_version=SCHEMA_VERSION, recording="x",
        dock_sn="D", drone_sn=None,
        started_at_ms=1700000000000, ended_at_ms=1700000420000,
        duration_ms=420000, total_envelopes=0,
        envelope_counts_by_topic_key={},
        phase_transitions=[], verdicts=[], alert_decisions=[],
        metrics=m, battery_samples=samples,
    )


class TestSpeedChart:
    def test_no_samples_placeholder(self) -> None:
        md = render_markdown(_make_report([]))
        assert "## 水平速度曲线" in md
        assert "## 垂直速度曲线" in md
        assert "无速度数据" in md

    def test_renders_dual_charts(self) -> None:
        """双版本: mermaid + ASCII, 两段都出."""
        samples = [
            BatterySample(rel_ms=0, percent=100, height_m=10, wind_ms=2.0,
                          horizontal_speed_ms=0.0, vertical_speed_ms=2.0),
            BatterySample(rel_ms=60_000, percent=85, height_m=30, wind_ms=3.0,
                          horizontal_speed_ms=8.5, vertical_speed_ms=0.5),
            BatterySample(rel_ms=120_000, percent=70, height_m=40, wind_ms=4.0,
                          horizontal_speed_ms=10.2, vertical_speed_ms=-1.5),
            BatterySample(rel_ms=180_000, percent=55, height_m=20, wind_ms=3.0,
                          horizontal_speed_ms=6.0, vertical_speed_ms=-2.5),
        ]
        md = render_markdown(_make_report(samples))
        assert "## 水平速度曲线" in md
        assert "## 垂直速度曲线" in md
        assert "```mermaid" in md
        assert "xychart-beta" in md
        assert "█" in md
        assert "m/s" in md

    def test_vertical_axis_has_negative(self) -> None:
        samples = [
            BatterySample(rel_ms=0, percent=100, height_m=40, wind_ms=2.0,
                          horizontal_speed_ms=5.0, vertical_speed_ms=1.0),
            BatterySample(rel_ms=60_000, percent=80, height_m=10, wind_ms=3.0,
                          horizontal_speed_ms=5.0, vertical_speed_ms=-3.0),
        ]
        md = render_markdown(_make_report(samples))
        assert "-3.0" in md                       # 垂直副图 y 轴底端负值 label
        assert "最大下降 3.0 m/s" in md

    def test_horizontal_summary_peak_avg(self) -> None:
        samples = [
            BatterySample(rel_ms=0, percent=100, height_m=10, wind_ms=2.0,
                          horizontal_speed_ms=4.0, vertical_speed_ms=0.0),
            BatterySample(rel_ms=60_000, percent=80, height_m=20, wind_ms=3.0,
                          horizontal_speed_ms=8.0, vertical_speed_ms=0.0),
        ]
        md = render_markdown(_make_report(samples))
        assert re.search(r"峰值 8\.0 m/s", md) is not None
        assert re.search(r"平均 6\.0 m/s", md) is not None

    def test_section_after_battery_before_wind(self) -> None:
        samples = [BatterySample(rel_ms=0, percent=80, height_m=10, wind_ms=2.0,
                                 horizontal_speed_ms=5.0, vertical_speed_ms=0.0)]
        md = render_markdown(_make_report(samples))
        i_batt = md.find("## 电池曲线")
        i_h = md.find("## 水平速度曲线")
        i_wind = md.find("## 风速曲线")
        assert 0 < i_batt < i_h < i_wind
