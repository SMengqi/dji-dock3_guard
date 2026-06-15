"""Stage 5-F Task 7: e2e against real sim recording.

依赖 root conftest.py `recording` fixture (sim 公开样本).
先跑 Stage 4-E 出 v3 report.json, 再跑 Stage 5-F.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import textwrap

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


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
          - dock_sn: 8UUXN7N00A0GAA
            enabled: true
    """))
    return cfg


class TestE2E:
    def test_real_recording_produces_yaml(
        self, recording: pathlib.Path, tmp_path: pathlib.Path,
    ) -> None:
        cfg = _seed_config(tmp_path)
        parent = tmp_path / "recordings"
        parent.mkdir()
        target = parent / recording.name
        target.symlink_to(recording)
        # 先 Stage 4-E (--force 升 v3)
        subprocess.run(
            [sys.executable, "-m", "dock_guard.analytics",
             str(target), "--config-dir", str(cfg), "--force", "--quiet"],
            check=True, cwd=str(REPO_ROOT),
        )
        # 再 Stage 5-F (--min-samples 5 让单录制也产桶)
        r = subprocess.run(
            [sys.executable, "-m", "dock_guard.analytics.analyzers.battery",
             str(parent), "--min-samples", "5"],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        assert r.returncode in (0, 1), r.stderr
        yaml_path = parent / "battery_analysis" / "battery_reference.yaml"
        assert yaml_path.exists()
        d = yaml.safe_load(yaml_path.read_text())
        assert d["schema_version"] == 1
        # 至少 1 桶有数据 (非 insufficient_data)
        ok = [b for b in d["buckets"] if b.get("status") != "insufficient_data"]
        assert len(ok) >= 1
