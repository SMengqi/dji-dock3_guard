"""Stage 5-F: 跨架次 markdown + yaml writer (设计 §6 §11).

render_battery_yaml: BatteryReference -> yaml string (battery_reference.yaml)
render_battery_markdown: BatteryReference + 异常列表 -> markdown
"""

from __future__ import annotations

from io import StringIO

import yaml

from dock_guard.analytics.analyzers.battery_buckets import (
    HEIGHT_BREAK,
    SOC_BREAKS,
    WIND_BREAKS,
)
from dock_guard.analytics.analyzers.battery_models import (
    BatteryReference,
    FlightAnomalyResult,
)


def render_battery_yaml(ref: BatteryReference) -> str:
    """生成 battery_reference.yaml 字符串 (设计 §6 schema)."""
    payload = {
        "schema_version": 1,
        "generated_at_ms": ref.generated_at_ms,
        "generated_by": {
            "recording_count": ref.recording_count,
            "total_sample_count": ref.total_sample_count,
        },
        "fit": {
            "algorithm": "piecewise_linear_3seg_ols",
            "soc_breakpoints": SOC_BREAKS,
            "wind_breakpoints": WIND_BREAKS,
            "height_break": HEIGHT_BREAK,
            "smoothing_window_s": 30,
        },
        "buckets": _serialize_buckets(ref),
    }
    out = StringIO()
    yaml.safe_dump(payload, out, sort_keys=False, allow_unicode=True,
                   default_flow_style=False)
    return out.getvalue()


def _serialize_buckets(ref: BatteryReference) -> list[dict]:
    out = []
    for key, stats in sorted(ref.buckets.items()):
        entry: dict = {"bucket_key": key, "sample_count": stats.sample_count}
        if stats.status == "insufficient_data":
            entry["status"] = "insufficient_data"
        else:
            entry["discharge_rate_pct_per_sec"] = {
                "mean": stats.mean, "p50": stats.p50,
                "p95": stats.p95, "p99": stats.p99, "max": stats.max,
            }
            entry["fit_quality"] = {
                "residual_std": stats.residual_std,
                "r_squared": stats.r_squared,
            }
        out.append(entry)
    return out


def render_battery_markdown(
    ref: BatteryReference,
    anomalies: list[FlightAnomalyResult],
    *,
    skipped_v2_count: int = 0,
) -> str:
    parts = ["# 电池基线分析报告", ""]
    parts.extend(_data_range(ref, skipped_v2_count))
    parts.append("")
    parts.extend(_occupancy(ref))
    parts.append("")
    parts.extend(_anomalies_section(anomalies))
    parts.append("")
    parts.extend(_fit_quality(ref))
    parts.append("")
    parts.append("---")
    parts.append("> 报告由 dock_guard.analytics.analyzers.battery 生成 · "
                 "schema v1 · 仅供人工分析, 不接实时规则")
    return "\n".join(parts) + "\n"


def _data_range(ref: BatteryReference, skipped: int) -> list[str]:
    return [
        "## 数据范围", "",
        f"- **录制总数:** {ref.recording_count} (跳过 v2 旧报告: {skipped})",
        f"- **采样总数:** {ref.total_sample_count} 个 10s 样本",
    ]


def _occupancy(ref: BatteryReference) -> list[str]:
    lines = ["## 桶占用情况", "", "| 桶 | sample_count | 状态 |", "|---|---|---|"]
    for key, stats in sorted(ref.buckets.items()):
        status = "insufficient_data" if stats.status == "insufficient_data" else "ok"
        lines.append(f"| {key} | {stats.sample_count} | {status} |")
    return lines


def _anomalies_section(anomalies: list[FlightAnomalyResult]) -> list[str]:
    bad = [a for a in anomalies if a.is_anomaly]
    total = max(1, len(anomalies))
    lines = [
        f"## 异常架次清单 ({len(bad)} / {len(anomalies)} 架次, "
        f"{100 * len(bad) / total:.1f}%)", "",
    ]
    if not bad:
        lines.append("(无异常架次)")
        return lines
    lines.append("| 录制 | 飞机 SN | DOCK SN | RED / 总 | YELLOW |")
    lines.append("|---|---|---|---|---|")
    for a in bad[:50]:
        lines.append(
            f"| {a.recording} | {a.drone_sn or '-'} | {a.dock_sn} | "
            f"{a.red_count} / {a.sample_count} | {a.yellow_count} |"
        )
    return lines


def _fit_quality(ref: BatteryReference) -> list[str]:
    lines = ["## 拟合质量", "", "| 桶 | R² | residual_std |", "|---|---|---|"]
    for key, stats in sorted(ref.buckets.items()):
        if stats.status == "insufficient_data":
            lines.append(f"| {key} | - | - |")
        else:
            lines.append(f"| {key} | {stats.r_squared:.2f} | {stats.residual_std:.3f} |")
    return lines
