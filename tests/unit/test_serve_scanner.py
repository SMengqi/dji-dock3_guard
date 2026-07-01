"""serve.scanner: 扫盘清单 + 容错 + 路径安全."""

from __future__ import annotations

from pathlib import Path

from dock_guard.analytics.serve.scanner import resolve_report, scan_reports
from tests.unit._serve_helpers import write_sample_report


def test_scan_lists_ok_report(tmp_path: Path) -> None:
    write_sample_report(tmp_path, "rec1")
    rows = scan_reports(tmp_path)
    assert len(rows) == 1
    r = rows[0]
    assert r["ok"] is True
    assert r["recording"] == "rec1"
    assert r["dock_sn"] == "DOCK_SN"
    assert r["min_battery_percent"] == 41
    assert r["peak_wind_gust_30s"] == 8.3


def test_scan_sorted_and_skips_non_report_dirs(tmp_path: Path) -> None:
    write_sample_report(tmp_path, "b_rec")
    write_sample_report(tmp_path, "a_rec")
    (tmp_path / "loose_dir").mkdir()  # 无 dock_guard_report/report.json
    rows = scan_reports(tmp_path)
    assert [r["recording"] for r in rows] == ["a_rec", "b_rec"]


def test_scan_marks_old_schema(tmp_path: Path) -> None:
    write_sample_report(tmp_path, "old", schema=2)
    rows = scan_reports(tmp_path)
    assert rows[0]["ok"] is False
    assert "v2" in rows[0]["error"]


def test_scan_marks_corrupt_json(tmp_path: Path) -> None:
    out = tmp_path / "bad" / "dock_guard_report"
    out.mkdir(parents=True)
    (out / "report.json").write_text("{not json", encoding="utf-8")
    rows = scan_reports(tmp_path)
    assert rows[0]["ok"] is False


def test_resolve_ok(tmp_path: Path) -> None:
    write_sample_report(tmp_path, "rec1")
    p = resolve_report(tmp_path, "rec1")
    assert p is not None and p.name == "report.json" and p.exists()


def test_resolve_rejects_traversal_and_missing(tmp_path: Path) -> None:
    write_sample_report(tmp_path, "rec1")
    assert resolve_report(tmp_path, "../etc") is None
    assert resolve_report(tmp_path, "a/b") is None
    assert resolve_report(tmp_path, "nope") is None


def test_resolve_rejects_nul_byte(tmp_path: Path) -> None:
    write_sample_report(tmp_path, "rec1")
    assert resolve_report(tmp_path, "a\x00b") is None


def test_scan_accepts_v4(tmp_path: Path) -> None:
    write_sample_report(tmp_path, "v4rec", schema=4)
    rows = scan_reports(tmp_path)
    assert rows[0]["ok"] is True
