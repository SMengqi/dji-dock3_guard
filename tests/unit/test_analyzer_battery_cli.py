"""Stage 5-F Task 7: battery analyzer CLI 单测.

谁运行: pytest discover. 同义文件: 无.
数据: tmp_path 合成 v3/v2 report.json (sim Stage 4-E 格式).
用户指令: "依次接着做, 做完记得提交, 不用每个都停".
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _make_v3(dst: pathlib.Path, n: int = 60) -> pathlib.Path:
    dst.mkdir(parents=True, exist_ok=True)
    inner = dst / "dock_guard_report"
    inner.mkdir(parents=True, exist_ok=True)
    samples = []
    pct = 95
    for i in range(n):
        samples.append({
            "rel_ms": i * 10_000, "percent": pct,
            "height_m": 30 + (i % 5), "wind_ms": 2.0 + (i % 3) * 0.5,
        })
        pct = max(0, pct - 1)
    (inner / "report.json").write_text(json.dumps({
        "schema_version": 3, "recording": dst.name,
        "dock_sn": "TEST_DOCK_01", "drone_sn": "TEST_DRONE_01",
        "started_at_ms": 0, "ended_at_ms": n * 10_000,
        "duration_ms": n * 10_000, "total_envelopes": 0,
        "envelope_counts_by_topic_key": {},
        "phase_transitions": [], "verdicts": [], "alert_decisions": [],
        "metrics": {
            "peak_wind_gust_30s": None, "peak_wind_gust_30s_at_ms": None,
            "min_battery_percent": pct, "min_battery_percent_at_ms": None,
            "longest_offline_ms": 0, "flight_duration_ms": 0,
            "total_verdicts": 0, "total_dispatched": 0, "total_suppressed": 0,
            "verdicts_by_code": {},
        },
        "battery_samples": samples,
    }), encoding="utf-8")
    return dst


def _make_v2(dst: pathlib.Path) -> pathlib.Path:
    dst.mkdir(parents=True, exist_ok=True)
    inner = dst / "dock_guard_report"
    inner.mkdir(parents=True, exist_ok=True)
    (inner / "report.json").write_text(json.dumps({
        "schema_version": 2, "recording": dst.name,
    }), encoding="utf-8")
    return dst


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "dock_guard.analytics.analyzers.battery", *args],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )


class TestCli:
    def test_produces_yaml_and_md(self, tmp_path: pathlib.Path) -> None:
        parent = tmp_path / "recordings"
        for i in range(5):
            _make_v3(parent / f"rec_{i}")
        r = _run(str(parent), "--min-samples", "10")
        assert r.returncode in (0, 1), r.stderr
        out = parent / "battery_analysis"
        assert (out / "battery_reference.yaml").exists()
        assert (out / "report.md").exists()

    def test_no_v3_exit_2(self, tmp_path: pathlib.Path) -> None:
        parent = tmp_path / "recordings"
        _make_v2(parent / "old")
        assert _run(str(parent)).returncode == 2

    def test_skips_v2(self, tmp_path: pathlib.Path) -> None:
        parent = tmp_path / "recordings"
        _make_v2(parent / "old")
        for i in range(5):
            _make_v3(parent / f"rec_{i}")
        r = _run(str(parent), "--min-samples", "10")
        # exit 1 (有 v2 跳过) 但 yaml 仍出
        assert r.returncode == 1, r.stderr
        assert (parent / "battery_analysis" / "battery_reference.yaml").exists()

    def test_out_overrides(self, tmp_path: pathlib.Path) -> None:
        parent = tmp_path / "recordings"
        for i in range(5):
            _make_v3(parent / f"rec_{i}")
        out = tmp_path / "results"
        r = _run(str(parent), "--out", str(out), "--min-samples", "10")
        assert r.returncode in (0, 1)
        assert (out / "battery_reference.yaml").exists()
