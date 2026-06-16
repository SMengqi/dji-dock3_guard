"""Stage 5-F Task 2: 单架次报告的电池 ASCII 曲线段单测.

谁运行: pytest discover. 同义文件: 无. 数据: 纯合成 FlightReport (含 BatterySample).
用户指令: "commit T1 然后开 T2".
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
        verdicts_by_code={},
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


class TestBatteryChart:
    def test_no_samples_placeholder(self) -> None:
        md = render_markdown(_make_report([]))
        assert "## 电池曲线" in md
        assert "无电池数据" in md or "无数据" in md

    def test_samples_render_ascii(self) -> None:
        samples = [
            BatterySample(rel_ms=0,       percent=100, height_m=10, wind_ms=2),
            BatterySample(rel_ms=60_000,  percent=85,  height_m=20, wind_ms=3),
            BatterySample(rel_ms=300_000, percent=25,  height_m=30, wind_ms=4),
        ]
        md = render_markdown(_make_report(samples))
        assert "## 电池曲线" in md
        assert "█" in md
        # 折线图 Y 轴含 100% 和 0% 两个端点
        assert "100%" in md
        assert "0%" in md
        # X 轴 5 分钟 -> "5m"
        assert "5m" in md or "5min" in md

    def test_summary_avg_rate(self) -> None:
        """100% -> 40% in 5min => 12 %/min."""
        samples = [
            BatterySample(rel_ms=0,       percent=100, height_m=10, wind_ms=2),
            BatterySample(rel_ms=300_000, percent=40,  height_m=30, wind_ms=4),
        ]
        md = render_markdown(_make_report(samples))
        m = re.search(r"平均耗电速率[:\s]+(\d+\.?\d*)", md)
        assert m is not None
        assert 10.0 <= float(m.group(1)) <= 14.0

    def test_section_order(self) -> None:
        """段落顺序: 摘要 -> 关键指标 -> 电池曲线 -> 阶段时间线."""
        samples = [BatterySample(rel_ms=0, percent=80, height_m=10, wind_ms=2)]
        md = render_markdown(_make_report(samples))
        i_metrics = md.find("## 关键指标")
        i_battery = md.find("## 电池曲线")
        i_phase   = md.find("## 阶段时间线")
        assert 0 < i_metrics < i_battery < i_phase
