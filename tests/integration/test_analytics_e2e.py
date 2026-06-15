"""Stage 4-E Task 4: e2e against real sim recording.

谁运行: pytest discover. 同义文件: 无.
数据: 依赖 ../sim_dji_cloud_service/sim_dji_cloud/recordings/8UU..._20260605-165145/
(由 root conftest.py recording fixture 提供). 用户指令: "commit T3 然后继续 T4".
"""

from __future__ import annotations

import pathlib
import textwrap

import pytest

from dock_guard.analytics import collect
from dock_guard.analytics.report import render_markdown


def _seed_config(tmp_path: pathlib.Path) -> pathlib.Path:
    repo = pathlib.Path(__file__).resolve().parents[2] / "config"
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
    def test_report_schema_v2_with_real_recording(
        self, recording: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        cfg = _seed_config(tmp_path)
        rep = collect(recording, cfg)
        d = rep.to_dict()
        assert d["schema_version"] == 3
        assert d["dock_sn"] == "8UUXN7N00A0GAA"
        codes = set(d["metrics"]["verdicts_by_code"].keys())
        # demo 模式阈值在真实录制上至少触发这俩
        assert "PREFLIGHT_DOCK_TILT" in codes
        assert "INFLIGHT_BATTERY_LOW" in codes

    def test_report_metrics_have_real_values(
        self, recording: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        cfg = _seed_config(tmp_path)
        rep = collect(recording, cfg)
        m = rep.metrics
        assert m.peak_wind_gust_30s is not None
        assert m.peak_wind_gust_30s > 0
        assert m.min_battery_percent is not None
        assert 0 <= m.min_battery_percent <= 100

    def test_markdown_contains_key_sections(
        self, recording: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        cfg = _seed_config(tmp_path)
        md = render_markdown(collect(recording, cfg))
        for section in ("## 摘要", "## 关键指标", "## 阶段时间线",
                        "## 告警时间线", "## 告警频次"):
            assert section in md
