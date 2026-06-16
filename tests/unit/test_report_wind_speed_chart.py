"""单架次报告"## 风速曲线"段单测.

谁运行: pytest discover. 同义文件: 无.
数据: 合成 BatterySample (含 wind_ms).
用户指令: "好的 已经看到风向分布图，能否将markdown中的电池、风向、风速 做成曲线图或折线图".
"""

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


class TestWindSpeedChart:
    def test_no_samples_placeholder(self) -> None:
        md = render_markdown(_make_report([]))
        assert "## 风速曲线" in md
        assert "无风速数据" in md or "无数据" in md

    def test_renders_dual_charts(self) -> None:
        """双版本: mermaid + ASCII."""
        samples = [
            BatterySample(rel_ms=0,       percent=100, height_m=10, wind_ms=2.0),
            BatterySample(rel_ms=60_000,  percent=85,  height_m=20, wind_ms=4.5),
            BatterySample(rel_ms=120_000, percent=70,  height_m=30, wind_ms=8.2),
            BatterySample(rel_ms=180_000, percent=55,  height_m=40, wind_ms=6.0),
            BatterySample(rel_ms=240_000, percent=40,  height_m=50, wind_ms=3.5),
        ]
        md = render_markdown(_make_report(samples))
        assert "## 风速曲线" in md
        # Mermaid
        assert "```mermaid" in md
        assert "xychart-beta" in md
        # ASCII
        assert "█" in md
        assert "m/s" in md

    def test_summary_peak_and_avg(self) -> None:
        """峰值 + 平均摘要行."""
        samples = [
            BatterySample(rel_ms=0,       percent=100, height_m=10, wind_ms=2.0),
            BatterySample(rel_ms=60_000,  percent=80,  height_m=20, wind_ms=8.0),
        ]
        md = render_markdown(_make_report(samples))
        # 摘要含峰值 + 平均
        assert re.search(r"峰值阵风[:\s]+8\.0", md) is not None
        assert re.search(r"平均[:\s]+5\.0", md) is not None
