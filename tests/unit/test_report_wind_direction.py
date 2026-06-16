"""单架次报告"## 风向分布"段单测.

谁运行: pytest discover. 同义文件: 无. 数据: 合成 FlightMetrics + FlightReport.
用户指令: "A" (选风向分布直方图).
"""

from __future__ import annotations

import re

from dock_guard.analytics.models import (
    SCHEMA_VERSION,
    FlightMetrics,
    FlightReport,
)
from dock_guard.analytics.report import render_markdown


def _make_report(wd_seconds: dict[str, int]) -> FlightReport:
    m = FlightMetrics(
        peak_wind_gust_30s=None, peak_wind_gust_30s_at_ms=None,
        min_battery_percent=None, min_battery_percent_at_ms=None,
        longest_offline_ms=0, flight_duration_ms=0,
        total_verdicts=0, total_dispatched=0, total_suppressed=0,
        verdicts_by_code={},
        wind_direction_seconds=wd_seconds,
    )
    return FlightReport(
        schema_version=SCHEMA_VERSION, recording="x",
        dock_sn="D", drone_sn=None,
        started_at_ms=1700000000000, ended_at_ms=1700000420000,
        duration_ms=420000, total_envelopes=0,
        envelope_counts_by_topic_key={},
        phase_transitions=[], verdicts=[], alert_decisions=[],
        metrics=m, battery_samples=[],
    )


class TestWindDirectionSection:
    def test_empty_renders_placeholder(self) -> None:
        md = render_markdown(_make_report({}))
        assert "## 风向分布" in md
        assert "无风向数据" in md or "无数据" in md

    def test_renders_histogram(self) -> None:
        # 模拟飞行: 主导东北 (146 秒) + 西北 (104) + 东 (67) + 正北 (50)
        wd = {"1": 50, "2": 146, "3": 67, "8": 104}
        md = render_markdown(_make_report(wd))
        assert "## 风向分布" in md
        # 8 个方向中文名都该出现
        for cn in ("正北", "东北", "东", "东南", "南", "西南", "西", "西北"):
            assert cn in md
        # ASCII 直方图标记
        assert "█" in md
        # 数值
        assert "146" in md and "104" in md

    def test_shows_dominant_direction(self) -> None:
        wd = {"1": 50, "2": 146, "3": 67}   # 2=东北 最大
        md = render_markdown(_make_report(wd))
        m = re.search(r"主导风向[:\s]+(\S+)", md)
        assert m is not None
        assert "东北" in m.group(1)

    def test_zero_direction_renders_zero_percent(self) -> None:
        """未出现的方向显示 0%."""
        wd = {"2": 100}   # 只有东北
        md = render_markdown(_make_report(wd))
        # 应有 8 行: 7 个 0.0% + 1 个 100.0%
        assert "100.0%" in md
        assert md.count("0.0%") >= 7

    def test_section_order(self) -> None:
        """段落顺序: 关键指标 -> 电池曲线 -> 风向分布 -> 阶段时间线."""
        md = render_markdown(_make_report({"2": 100}))
        i_battery = md.find("## 电池曲线")
        i_wind = md.find("## 风向分布")
        i_phase = md.find("## 阶段时间线")
        assert 0 < i_battery < i_wind < i_phase
