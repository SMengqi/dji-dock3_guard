"""Stage 4-E Task 3: CLI single / batch / --out / --force / 错误路径.

谁运行: pytest discover. 同义文件: 无. 数据: 合成 manifest+jsonl (schema v1).
用户指令: "继续 T3".
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import textwrap
import time

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _make_recording(dst: pathlib.Path) -> pathlib.Path:
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "topics").mkdir()
    (dst / "topics" / "x.jsonl").write_text(json.dumps({
        "recv_ts_ms": 1000, "dji_ts_ms": 1000, "direction": "up",
        "topic": "sys/product/TEST_DOCK_01/status",
        "payload": {"sub_type": 0},
    }) + "\n", encoding="utf-8")
    (dst / "manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "dock_sn": "TEST_DOCK_01",
        "drone_sn": "TEST_DRONE_01",
        "started_at_recv_ms": 1000,
        "ended_at_recv_ms": 1000,
        "topics": [{
            "topic": "synthetic",
            "device_sn": "TEST_DOCK_01",
            "direction": "up",
            "count": 1,
            "first_recv_ts_ms": 1000,
            "last_recv_ts_ms": 1000,
            "files": [{"name": "topics/x.jsonl", "count": 1,
                       "first_ms": 1000, "last_ms": 1000}],
        }],
    }), encoding="utf-8")
    return dst


def _seed_config(tmp_path: pathlib.Path) -> pathlib.Path:
    repo = REPO_ROOT / "config"
    if not (repo / "mode_code_map.yaml").exists():
        pytest.skip("repo config not present")
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    for name in ("mode_code_map.yaml", "alert_levels.yaml", "enums.yaml", "rules.yaml"):
        (cfg / name).symlink_to(repo / name)
    (cfg / "runtime.yaml").write_text(textwrap.dedent("""
        schema_version: 1
        mqtt:
          broker_url:  tcp://test:1883
          username:    "x"
          password:    "x"
        subscriptions:
          - dock_sn: TEST_DOCK_01
            enabled: true
    """))
    return cfg


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "dock_guard.analytics", *args],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )


class TestSingleMode:
    def test_single_produces_report_files(self, tmp_path: pathlib.Path) -> None:
        cfg = _seed_config(tmp_path)
        rec = _make_recording(tmp_path / "rec_a")
        r = _run_cli(str(rec), "--config-dir", str(cfg))
        assert r.returncode == 0, r.stderr
        assert (rec / "dock_guard_report" / "report.json").exists()
        assert (rec / "dock_guard_report" / "report.md").exists()

    def test_single_report_json_has_schema_version(self, tmp_path: pathlib.Path) -> None:
        cfg = _seed_config(tmp_path)
        rec = _make_recording(tmp_path / "rec_a")
        _run_cli(str(rec), "--config-dir", str(cfg))
        d = json.loads((rec / "dock_guard_report" / "report.json").read_text())
        assert d["schema_version"] == 7
        assert d["dock_sn"] == "TEST_DOCK_01"


class TestBatchMode:
    def test_batch_processes_all_subdirs(self, tmp_path: pathlib.Path) -> None:
        cfg = _seed_config(tmp_path)
        parent = tmp_path / "recordings"
        _make_recording(parent / "rec_a")
        _make_recording(parent / "rec_b")
        r = _run_cli(str(parent), "--config-dir", str(cfg))
        assert r.returncode == 0, r.stderr
        assert (parent / "rec_a" / "dock_guard_report" / "report.json").exists()
        assert (parent / "rec_b" / "dock_guard_report" / "report.json").exists()
        assert (parent / "index.md").exists()

    def test_batch_index_md_lists_all(self, tmp_path: pathlib.Path) -> None:
        cfg = _seed_config(tmp_path)
        parent = tmp_path / "recordings"
        _make_recording(parent / "rec_a")
        _make_recording(parent / "rec_b")
        _run_cli(str(parent), "--config-dir", str(cfg))
        index = (parent / "index.md").read_text()
        assert "rec_a" in index and "rec_b" in index

    def test_batch_skips_already_analyzed(self, tmp_path: pathlib.Path) -> None:
        cfg = _seed_config(tmp_path)
        parent = tmp_path / "recordings"
        rec = _make_recording(parent / "rec_a")
        _run_cli(str(parent), "--config-dir", str(cfg))
        mtime0 = (rec / "dock_guard_report" / "report.json").stat().st_mtime
        time.sleep(0.05)
        _run_cli(str(parent), "--config-dir", str(cfg))
        assert (rec / "dock_guard_report" / "report.json").stat().st_mtime == mtime0


class TestOutOption:
    def test_out_writes_to_separate_dir(self, tmp_path: pathlib.Path) -> None:
        cfg = _seed_config(tmp_path)
        rec = _make_recording(tmp_path / "rec_a")
        out = tmp_path / "reports_out"
        r = _run_cli(str(rec), "--config-dir", str(cfg), "--out", str(out))
        assert r.returncode == 0
        assert not (rec / "dock_guard_report").exists()
        assert (out / "rec_a" / "report.json").exists()


class TestErrorPaths:
    def test_nonexistent_path_exit_2(self, tmp_path: pathlib.Path) -> None:
        cfg = _seed_config(tmp_path)
        r = _run_cli(str(tmp_path / "nope"), "--config-dir", str(cfg))
        assert r.returncode == 2

    def test_corrupt_recording_in_batch_marks_warning(
        self, tmp_path: pathlib.Path
    ) -> None:
        cfg = _seed_config(tmp_path)
        parent = tmp_path / "recordings"
        _make_recording(parent / "rec_a")
        bad = parent / "bad_rec"
        bad.mkdir(parents=True)
        (bad / "manifest.json").write_text("{NOT_JSON}")
        r = _run_cli(str(parent), "--config-dir", str(cfg))
        assert r.returncode == 1
        index = (parent / "index.md").read_text()
        assert "⚠️" in index and "bad_rec" in index
        assert (parent / "rec_a" / "dock_guard_report" / "report.json").exists()

    def test_existing_v2_report_friendly_error(
        self, tmp_path: pathlib.Path
    ) -> None:
        """老 v2 report.json (无 battery_samples) -> index.md 友好提示 + 不泄 Python 错."""
        cfg = _seed_config(tmp_path)
        parent = tmp_path / "recordings"
        rec = _make_recording(parent / "rec_old")
        # 注入 Stage 4-E 时代的 v2 report.json (无 battery_samples 字段)
        dgr = rec / "dock_guard_report"
        dgr.mkdir(parents=True, exist_ok=True)
        (dgr / "report.json").write_text(json.dumps({
            "schema_version": 2, "recording": "rec_old",
            "dock_sn": "TEST_DOCK_01", "drone_sn": None,
            "started_at_ms": 0, "ended_at_ms": 1000, "duration_ms": 1000,
            "total_envelopes": 0, "envelope_counts_by_topic_key": {},
            "phase_transitions": [], "verdicts": [], "alert_decisions": [],
            "metrics": {
                "peak_wind_gust_30s": None, "peak_wind_gust_30s_at_ms": None,
                "min_battery_percent": None, "min_battery_percent_at_ms": None,
                "longest_offline_ms": 0, "flight_duration_ms": 0,
                "total_verdicts": 0, "total_dispatched": 0, "total_suppressed": 0,
                "verdicts_by_code": {},
            },
        }), encoding="utf-8")
        r = _run_cli(str(parent), "--config-dir", str(cfg))
        assert r.returncode == 1   # 至少 1 个 ⚠️
        index = (parent / "index.md").read_text()
        assert "rec_old" in index
        assert "⚠️" in index
        # 友好提示, 不是裸 Python 错
        assert "v2" in index and "--force" in index
        # 老 Python error message 不应泄露
        assert "missing 1 required positional argument" not in index
