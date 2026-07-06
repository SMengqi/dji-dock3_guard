"""扫 reports_root → 报告摘要清单 + 路径安全解析 (只读).

磁盘布局: <reports_root>/<recording>/dock_guard_report/report.json
report.json = analytics.models.FlightReport.to_dict() (schema v3/v4/v5).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_SCHEMA_OK = frozenset({3, 4, 5, 6, 7})
_SUBPATH = ("dock_guard_report", "report.json")


def scan_reports(reports_root: Path) -> list[dict[str, Any]]:
    """扫全部 <root>/*/dock_guard_report/report.json → 摘要清单 (按名排序).

    损坏 / 非 v3/v4/v5/v6 的报告标 {"ok": False, "error": ...}, 不抛.
    """
    rows: list[dict[str, Any]] = []
    if not reports_root.is_dir():
        return rows
    for sub in sorted(reports_root.iterdir(), key=lambda p: p.name):
        if not sub.is_dir():
            continue
        rp = sub.joinpath(*_SUBPATH)
        if not rp.is_file():
            continue
        rows.append(_summarize(sub.name, rp))
    return rows


def _summarize(recording: str, rp: Path) -> dict[str, Any]:
    try:
        d = json.loads(rp.read_text(encoding="utf-8"))
    except Exception as e:  # 容错: 任意坏文件都标记不崩
        return {"recording": recording, "ok": False, "error": f"解析失败: {e}"}
    schema = d.get("schema_version", 0)
    if schema not in _SCHEMA_OK:
        return {
            "recording": recording,
            "ok": False,
            "error": f"schema v{schema} 旧报告 (需 v3/v4/v5/v6)",
        }
    m = d.get("metrics", {})
    return {
        "recording": recording,
        "ok": True,
        "dock_sn": d.get("dock_sn"),
        "drone_sn": d.get("drone_sn"),
        "duration_ms": d.get("duration_ms"),
        "min_battery_percent": m.get("min_battery_percent"),
        "peak_wind_gust_30s": m.get("peak_wind_gust_30s"),
    }


def resolve_report(reports_root: Path, recording: str) -> Path | None:
    """安全解析 recording → report.json 绝对路径. 非法/穿越/缺失返 None."""
    if not recording or "/" in recording or "\\" in recording or ".." in recording:
        return None
    try:
        root = reports_root.resolve()
        rp = root.joinpath(recording, *_SUBPATH).resolve()
    except (OSError, ValueError):
        return None
    if root not in rp.parents:
        return None
    if not rp.is_file():
        return None
    return rp
