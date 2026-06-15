"""Stage 4-E Task 2: report 渲染单测.

谁运行: pytest discover. 同义文件: 无 (Glob 已确认). 数据: 纯合成 FlightReport
实例 (sim 公开样本 SN, 非生产). 用户指令: "继续 T2".
"""

from __future__ import annotations

import json

from dock_guard.analytics.models import (
    SCHEMA_VERSION,
    FlightMetrics,
    FlightReport,
)
from dock_guard.analytics.report import (
    render_index_md,
    render_json,
    render_markdown,
)


def _make_report(**overrides) -> FlightReport:
    metrics = FlightMetrics(
        peak_wind_gust_30s=6.5,
        peak_wind_gust_30s_at_ms=1700000004000,
        min_battery_percent=39,
        min_battery_percent_at_ms=1700000005000,
        longest_offline_ms=2300,
        flight_duration_ms=312000,
        total_verdicts=4660,
        total_dispatched=24,
        total_suppressed=4636,
        verdicts_by_code={
            "INFLIGHT_BATTERY_LOW": 2055,
            "INFLIGHT_WIND_GUST": 1963,
            "PREFLIGHT_DOCK_TILT": 165,
        },
    )
    base = dict(
        schema_version=SCHEMA_VERSION,
        recording="8UUXN7N00A0GAA_20260605-165145",
        dock_sn="8UUXN7N00A0GAA",
        drone_sn="1581F8HGX257Q00A0PSH",
        started_at_ms=1700000000000,
        ended_at_ms=1700000410833,
        duration_ms=410833,
        total_envelopes=2739,
        envelope_counts_by_topic_key={"dock_osd": 818, "drone_osd": 206},
        phase_transitions=[
            {"ts_ms": 1700000012000, "phase_from": "IDLE", "phase_to": "PREFLIGHT",
             "phase_source_from": "fallback_idle", "phase_source_to": "flighttask_step_code",
             "reason": "task started", "mode_code": 0, "drone_in_dock": 1, "warnings": []},
            {"ts_ms": 1700000028000, "phase_from": "PREFLIGHT", "phase_to": "CRUISE",
             "phase_source_from": "flighttask_step_code", "phase_source_to": "flighttask_step_code",
             "reason": "takeoff", "mode_code": 5, "drone_in_dock": 0, "warnings": []},
        ],
        verdicts=[
            {"ts_ms": 1700000028500, "rule_id": "PREFLIGHT_DOCK_TILT", "code": "PREFLIGHT_DOCK_TILT",
             "level": "BLOCK", "phase_when_fired": "PREFLIGHT",
             "phase_source_when_fired": "flighttask_step_code",
             "suggested_action": "reject_takeoff", "dedup_key": "x"},
        ],
        alert_decisions=[
            {"ts_ms": 1700000028500, "code": "PREFLIGHT_DOCK_TILT",
             "level": "BLOCK", "decision": "DISPATCHED", "gates": {"mute": "pass"}},
        ],
        metrics=metrics,
    )
    base.update(overrides)
    return FlightReport(**base)


class TestRenderJson:
    def test_returns_valid_json_with_schema_version(self) -> None:
        s = render_json(_make_report())
        d = json.loads(s)
        assert d["schema_version"] == SCHEMA_VERSION
        assert d["recording"] == "8UUXN7N00A0GAA_20260605-165145"
        assert d["metrics"]["peak_wind_gust_30s"] == 6.5


class TestRenderMarkdown:
    def test_contains_summary_section(self) -> None:
        md = render_markdown(_make_report())
        assert "# 飞行复盘报告" in md
        assert "## 摘要" in md
        assert "8UUXN7N00A0GAA" in md

    def test_contains_metrics(self) -> None:
        md = render_markdown(_make_report())
        assert "## 关键指标" in md
        assert "6.5" in md
        assert "39%" in md
        assert "2.3" in md   # longest offline 秒数

    def test_contains_phase_timeline_with_gantt(self) -> None:
        md = render_markdown(_make_report())
        assert "## 阶段时间线" in md
        assert "█" in md and "░" in md

    def test_contains_alert_tables(self) -> None:
        md = render_markdown(_make_report())
        assert "## 告警时间线" in md
        assert "## 告警频次" in md
        assert "PREFLIGHT_DOCK_TILT" in md

    def test_zero_envelope_report_renders(self) -> None:
        empty_metrics = FlightMetrics(
            peak_wind_gust_30s=None, peak_wind_gust_30s_at_ms=None,
            min_battery_percent=None, min_battery_percent_at_ms=None,
            longest_offline_ms=0, flight_duration_ms=0,
            total_verdicts=0, total_dispatched=0, total_suppressed=0,
            verdicts_by_code={},
        )
        rep = _make_report(
            total_envelopes=0,
            envelope_counts_by_topic_key={},
            phase_transitions=[], verdicts=[], alert_decisions=[],
            metrics=empty_metrics,
        )
        md = render_markdown(rep)
        assert "无数据" in md or "（无" in md


class TestRenderIndexMd:
    def test_index_contains_summary_row_per_report(self) -> None:
        reports = [
            ("8UUXN7N00A0GAA_20260605-165145", _make_report(), None),
            ("8UUXN7N00A0GAA_20260606-091230", _make_report(
                recording="8UUXN7N00A0GAA_20260606-091230",
                started_at_ms=1700100000000,
                ended_at_ms=1700100252000,
                duration_ms=252000,
            ), None),
        ]
        md = render_index_md(reports)
        assert "# 飞行复盘索引" in md
        assert "8UUXN7N00A0GAA_20260605-165145" in md
        assert "8UUXN7N00A0GAA_20260606-091230" in md
        assert "✅" in md

    def test_index_marks_failed_recordings(self) -> None:
        md = render_index_md([("BAD_RECORDING", None, "manifest.json 解析失败")])
        assert "BAD_RECORDING" in md
        assert "⚠️" in md
        assert "manifest.json 解析失败" in md
