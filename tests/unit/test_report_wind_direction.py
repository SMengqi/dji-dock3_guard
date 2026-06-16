"""单架次报告"## 风向时序"段单测.

谁运行: pytest discover. 同义文件: 无.
数据: 合成 BatterySample 带 wind_direction 字段.
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


class TestWindDirectionChart:
    def test_no_samples_placeholder(self) -> None:
        md = render_markdown(_make_report([]))
        assert "## 风向时序" in md
        assert "无风向数据" in md or "无数据" in md

    def test_samples_without_direction_placeholder(self) -> None:
        """有 battery_samples 但全部 wind_direction=None -> 占位."""
        samples = [
            BatterySample(rel_ms=0, percent=80, height_m=10, wind_ms=2.0,
                          wind_direction=None),
        ]
        md = render_markdown(_make_report(samples))
        assert "## 风向时序" in md
        assert "无风向数据" in md or "无数据" in md

    def test_renders_dual_charts(self) -> None:
        """双版本: mermaid bar (分布) + ASCII 时序."""
        samples = [
            BatterySample(rel_ms=0,       percent=100, height_m=10, wind_ms=2,
                          wind_direction=1),  # N
            BatterySample(rel_ms=60_000,  percent=85,  height_m=20, wind_ms=3,
                          wind_direction=2),  # NE
            BatterySample(rel_ms=120_000, percent=70,  height_m=30, wind_ms=3,
                          wind_direction=2),  # NE
            BatterySample(rel_ms=180_000, percent=55,  height_m=40, wind_ms=4,
                          wind_direction=3),  # E
            BatterySample(rel_ms=240_000, percent=40,  height_m=50, wind_ms=5,
                          wind_direction=8),  # NW
        ]
        md = render_markdown(_make_report(samples))
        assert "## 风向时序" in md
        # Mermaid bar chart
        assert "```mermaid" in md
        assert "xychart-beta" in md
        assert "bar " in md
        # ASCII 时序保留
        assert "█" in md
        for en in ("N", "NE", "E", "SE", "S", "SW", "W", "NW"):
            assert en in md

    def test_dominant_direction_summary(self) -> None:
        """主导风向: 出现最多的方向."""
        samples = [
            BatterySample(rel_ms=i * 10_000, percent=90, height_m=20, wind_ms=3,
                          wind_direction=2 if i < 3 else 5)
            for i in range(5)
        ]   # 3 个 NE + 2 个 S -> 主导 NE
        md = render_markdown(_make_report(samples))
        m = re.search(r"主导风向[:\s]+(\S+)", md)
        assert m is not None
        assert "东北" in m.group(1)
