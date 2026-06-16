"""Stage 4-E: 报告渲染 (设计 §8).

render_json: FlightReport -> JSON string (落盘 report.json)
render_markdown: FlightReport -> markdown (含 ASCII Gantt)
render_index_md: list[(name, FlightReport|None, error|None)] -> 父目录索引
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime

from dock_guard.analytics.models import FlightReport

# 跟 dingtalk.py 同口径的译名
_SEV_CN = {"EMERGENCY": "紧急", "BLOCK": "拦阻", "RETURN": "召回",
           "WARN": "警告", "INFO": "提示"}
_PHASE_CN = {"IDLE": "待机", "PREFLIGHT": "起飞前", "TAKEOFF": "起飞中",
             "CRUISE": "巡航中", "AVOIDANCE": "避障中", "RTH": "返航中",
             "LANDING": "降落中", "POSTFLIGHT": "落地后",
             "OFFLINE": "离线", "UPGRADING": "升级中"}
_ACTION_CN = {"reject_takeoff": "🛑 拒绝起飞", "return_home": "🔙 立即返航",
              "notify": "📋 仅记录", "investigate": "🔍 现场检查"}

_GANTT_MAX_COLS = 60


def render_json(rep: FlightReport) -> str:
    return json.dumps(rep.to_dict(), ensure_ascii=False, indent=2) + "\n"


def render_markdown(rep: FlightReport) -> str:
    parts: list[str] = []
    parts.append(f"# 飞行复盘报告 — {rep.recording}\n")
    parts.extend(_render_summary(rep))
    parts.append("")
    parts.extend(_render_metrics(rep))
    parts.append("")
    parts.extend(_render_battery_chart(rep))
    parts.append("")
    parts.extend(_render_wind_direction(rep))
    parts.append("")
    parts.extend(_render_phase_timeline(rep))
    parts.append("")
    parts.extend(_render_alerts_timeline(rep))
    parts.append("")
    parts.extend(_render_alert_counts(rep))
    parts.append("")
    parts.append("---")
    parts.append(f"> 报告由 dock_guard.analytics 生成 · schema v{rep.schema_version} · 不下发指令, 仅供人工复盘")
    return "\n".join(parts) + "\n"


def render_index_md(rows: list[tuple[str, FlightReport | None, str | None]]) -> str:
    out: list[str] = []
    out.append("# 飞行复盘索引")
    out.append("")
    out.append("| 录制 | 机场 | 飞机 | 时长 | DISPATCHED | 最低电量 | 阵风峰值 | 状态 |")
    out.append("|---|---|---|---|---|---|---|---|")
    success_count = fail_count = total_flight_ms = total_dispatched = 0
    for name, rep, err in rows:
        if rep is None:
            fail_count += 1
            out.append(f"| {name} | - | - | - | - | - | - | ⚠️ {err or '未知错误'} |")
            continue
        success_count += 1
        total_flight_ms += rep.metrics.flight_duration_ms
        total_dispatched += rep.metrics.total_dispatched
        wind = (f"{rep.metrics.peak_wind_gust_30s:.1f} m/s"
                if rep.metrics.peak_wind_gust_30s is not None else "-")
        batt = (f"{rep.metrics.min_battery_percent}%"
                if rep.metrics.min_battery_percent is not None else "-")
        link = f"[{name}](./{name}/dock_guard_report/report.md)"
        out.append(
            f"| {link} | {rep.dock_sn} | {rep.drone_sn or '-'} | "
            f"{_format_duration(rep.duration_ms)} | {rep.metrics.total_dispatched} | "
            f"{batt} | {wind} | ✅ |"
        )
    out.append("")
    out.append(
        f"**汇总：** {success_count} 份成功, {fail_count} 份失败. "
        f"总飞行 {_format_duration(total_flight_ms)}, 总 DISPATCHED {total_dispatched} 条."
    )
    out.append("")
    out.append("> 索引由 dock_guard.analytics 生成 · schema v2")
    return "\n".join(out) + "\n"


def _render_summary(rep: FlightReport) -> list[str]:
    return [
        "## 摘要",
        "",
        "| 项目 | 值 |",
        "|---|---|",
        f"| 机场 SN | {rep.dock_sn} |",
        f"| 飞机 SN | {rep.drone_sn or '无'} |",
        f"| 录制时长 | {_format_duration(rep.duration_ms)}({rep.duration_ms / 1000:.1f}s) |",
        f"| envelope 总数 | {rep.total_envelopes} |",
        f"| 飞行阶段切换 | {len(rep.phase_transitions)} 次 |",
        f"| 告警触发 | {rep.metrics.total_verdicts} 次(DISPATCHED {rep.metrics.total_dispatched} / SUPPRESSED {rep.metrics.total_suppressed}) |",
    ]


def _render_metrics(rep: FlightReport) -> list[str]:
    m = rep.metrics
    lines = ["## 关键指标", ""]
    if m.peak_wind_gust_30s is not None and m.peak_wind_gust_30s_at_ms is not None:
        rel_ms = m.peak_wind_gust_30s_at_ms - rep.started_at_ms
        utc = _format_utc(m.peak_wind_gust_30s_at_ms)
        lines.append(f"- **阵风峰值(30s 窗口):** {m.peak_wind_gust_30s:.1f} m/s "
                     f"@ +{_format_duration(rel_ms)}({utc} UTC)")
    else:
        lines.append("- **阵风峰值(30s 窗口):** 无数据")
    if m.min_battery_percent is not None and m.min_battery_percent_at_ms is not None:
        rel_ms = m.min_battery_percent_at_ms - rep.started_at_ms
        utc = _format_utc(m.min_battery_percent_at_ms)
        lines.append(f"- **最低电量:** {m.min_battery_percent}% "
                     f"@ +{_format_duration(rel_ms)}({utc} UTC)")
    else:
        lines.append("- **最低电量:** 无数据")
    lines.append(f"- **最长 OFFLINE 持续:** {m.longest_offline_ms / 1000:.1f} 秒")
    lines.append(f"- **飞行总时长(不含 OFFLINE/IDLE):** "
                 f"{_format_duration(m.flight_duration_ms)}({m.flight_duration_ms / 1000:.0f}s)")
    return lines


def _render_battery_chart(rep: FlightReport) -> list[str]:
    """Stage 5-F: 单架次 ASCII 电池曲线 (60 col 宽; 每行一个采样点)."""
    samples = rep.battery_samples
    if not samples:
        return ["## 电池曲线", "", "(无电池数据)"]

    lines = ["## 电池曲线", "", "```"]
    width = 60
    duration_min = max(1, (samples[-1].rel_ms - samples[0].rel_ms) // 60_000 + 1)
    step = max(1, len(samples) // duration_min) if duration_min > 0 else 1
    for s in samples[::step]:
        rel_min = s.rel_ms // 60_000
        pos = int(s.percent / 100 * (width - 1))
        row = ["░"] * width
        for i in range(max(0, pos - 2), min(width, pos + 2)):
            row[i] = "█"
        lines.append(f"  {s.percent:3d}% {''.join(row)}  +{rel_min}m")
    lines.append("```")
    lines.append("")
    if len(samples) >= 2:
        dp = samples[0].percent - samples[-1].percent
        dm = (samples[-1].rel_ms - samples[0].rel_ms) / 60_000
        if dm > 0:
            lines.append(f"平均耗电速率: {dp / dm:.1f} %/分钟")
    return lines


# wind_direction enum_int -> (英文缩写, 中文名)
_WIND_DIR_LABELS = [
    ("1", "N",  "正北"),
    ("2", "NE", "东北"),
    ("3", "E",  "东"),
    ("4", "SE", "东南"),
    ("5", "S",  "南"),
    ("6", "SW", "西南"),
    ("7", "W",  "西"),
    ("8", "NW", "西北"),
]


def _render_wind_direction(rep: FlightReport) -> list[str]:
    """风向分布直方图 (8 个方向, 按飞行秒数 + 百分比)."""
    wd = rep.metrics.wind_direction_seconds
    if not wd:
        return ["## 风向分布", "", "(无风向数据)"]

    total = sum(wd.values()) or 1
    bar_width = 26   # ASCII 条最大宽度
    lines = ["## 风向分布", "", "```"]
    dominant_key, dominant_sec = max(wd.items(), key=lambda kv: kv[1])
    for key, en, cn in _WIND_DIR_LABELS:
        sec = wd.get(key, 0)
        pct = 100 * sec / total
        filled = int(pct / 100 * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)
        marker = "  <- 主导" if key == dominant_key and sec > 0 else ""
        lines.append(f"  {cn:<3}  {en:<2}  {bar}  {pct:5.1f}% ({sec} 秒){marker}")
    lines.append("```")
    lines.append("")
    dominant_cn = next(cn for k, en, cn in _WIND_DIR_LABELS if k == dominant_key)
    lines.append(f"主导风向: {dominant_cn} ({dominant_sec} 秒)")
    return lines


def _render_phase_timeline(rep: FlightReport) -> list[str]:
    if not rep.phase_transitions:
        return ["## 阶段时间线", "", "(无阶段切换)"]
    intervals: list[tuple[str, int, int]] = [
        (rep.phase_transitions[0]["phase_from"], rep.started_at_ms,
         rep.phase_transitions[0]["ts_ms"])
    ]
    for i in range(len(rep.phase_transitions) - 1):
        cur, nxt = rep.phase_transitions[i], rep.phase_transitions[i + 1]
        intervals.append((cur["phase_to"], cur["ts_ms"], nxt["ts_ms"]))
    last = rep.phase_transitions[-1]
    intervals.append((last["phase_to"], last["ts_ms"], rep.ended_at_ms))

    total_s = max(int((rep.ended_at_ms - rep.started_at_ms) / 1000), 1)
    cols = min(_GANTT_MAX_COLS, total_s)
    sec_per_col = total_s / cols

    lines = ["## 阶段时间线", "", "```"]
    seen_phases: list[str] = []
    for phase, _, _ in intervals:
        if phase not in seen_phases:
            seen_phases.append(phase)
    for phase in seen_phases:
        row = ["░"] * cols
        rel_start = None
        for p, s_ts, e_ts in intervals:
            if p != phase:
                continue
            s_col = int((s_ts - rep.started_at_ms) / 1000 / sec_per_col)
            e_col = int((e_ts - rep.started_at_ms) / 1000 / sec_per_col)
            s_col = max(0, min(s_col, cols - 1))
            e_col = max(s_col + 1, min(e_col, cols))
            for c in range(s_col, e_col):
                row[c] = "█"
            if rel_start is None:
                rel_start = (s_ts - rep.started_at_ms) // 1000
        lines.append(f"  +{int(rel_start or 0):<5d} {phase:<11s} {''.join(row)}")
    lines.append(f"                       └{'─' * cols}┘")
    lines.append(f"                       0s{' ' * max(cols - 5, 1)}{total_s}s")
    lines.append("```")
    return lines


def _render_alerts_timeline(rep: FlightReport) -> list[str]:
    dispatched = [d for d in rep.alert_decisions if d["decision"] == "DISPATCHED"]
    lines = [f"## 告警时间线(DISPATCHED {len(dispatched)} 条)", ""]
    if not dispatched:
        lines.append("(无 DISPATCHED 告警)")
        return lines
    lines.append("| 时间 | 级别 | 告警代码 | 阶段 | 建议 |")
    lines.append("|---|---|---|---|---|")
    verdict_idx = {(v["ts_ms"], v["code"]): v for v in rep.verdicts}
    for d in dispatched[:50]:
        v = verdict_idx.get((d["ts_ms"], d["code"])) or {}
        rel_s = (d["ts_ms"] - rep.started_at_ms) / 1000
        sev = _SEV_CN.get(d["level"], d["level"])
        phase_raw = v.get("phase_when_fired", "?")
        phase_cn = _PHASE_CN.get(phase_raw, phase_raw)
        action_cn = _ACTION_CN.get(v.get("suggested_action", "?"),
                                   v.get("suggested_action", "?"))
        lines.append(f"| +{rel_s:.0f}s | {sev} | {d['code']} | {phase_cn} | {action_cn} |")
    if len(dispatched) > 50:
        lines.append(f"| ... | ... | (省略 {len(dispatched) - 50} 条) | ... | ... |")
    return lines


def _render_alert_counts(rep: FlightReport) -> list[str]:
    if not rep.metrics.verdicts_by_code:
        return ["## 告警频次", "", "(无告警)"]
    by_dec: Counter = Counter()
    for d in rep.alert_decisions:
        by_dec[(d["code"], d["decision"])] += 1
    lines = ["## 告警频次(含 SUPPRESSED)", "",
             "| 代码 | 触发 | DISPATCHED | SUPPRESSED |", "|---|---|---|---|"]
    for code, total in sorted(rep.metrics.verdicts_by_code.items(),
                              key=lambda x: -x[1]):
        lines.append(f"| {code} | {total} | "
                     f"{by_dec.get((code, 'DISPATCHED'), 0)} | "
                     f"{by_dec.get((code, 'SUPPRESSED'), 0)} |")
    return lines


def _format_duration(ms: int) -> str:
    if ms < 0:
        ms = 0
    total_s = ms // 1000
    m, s = divmod(total_s, 60)
    if m == 0:
        return f"{s} 秒"
    if total_s < 3600:
        return f"{m} 分 {s:02d} 秒"
    h, m = divmod(m, 60)
    return f"{h} 时 {m:02d} 分 {s:02d} 秒"


def _format_utc(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
