"""Stage 3-D B3 + Stage 4-E: replay baseline 兼容薄壳.

Stage 4-E 后 collector 真身搬到 src/dock_guard/analytics/collector.py;
baseline schema_version=1 (无 metrics), FlightReport schema_version=2;
本文件裁掉 metrics 字段, 让 tests/replay/test_replay_baseline.py 与
scripts/regen_replay_baseline.py 继续工作.

调用方:
- tests/replay/test_replay_baseline.py
- scripts/regen_replay_baseline.py
两者只用 run_replay_collect + stage_config_dir 这两个公开符号.
"""

from __future__ import annotations

import pathlib
import textwrap
from typing import Any

from dock_guard.analytics.collector import collect

SCHEMA_VERSION = 1


def stage_config_dir(dst: pathlib.Path, repo_config_dir: pathlib.Path) -> None:
    """合成最小 runtime.yaml + 复用仓库 mode_code_map/alert_levels/enums/rules.

    向后兼容签名: 跟 Stage 3-D B3 相同, 供 baseline 测试与 regen 脚本调用.
    """
    for name in ("mode_code_map.yaml", "alert_levels.yaml", "enums.yaml", "rules.yaml"):
        link = dst / name
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(repo_config_dir / name)
    (dst / "runtime.yaml").write_text(textwrap.dedent("""
        schema_version: 1
        mqtt:
          broker_url:  ${MQTT_BROKER_URL}
          username:    ${MQTT_USERNAME}
          password:    ${MQTT_PASSWORD}
        subscriptions:
          - dock_sn: ${MQTT_DOCK_SN}
            enabled: true
    """))


def run_replay_collect(
    recording_dir: pathlib.Path,
    config_dir: pathlib.Path,
) -> dict[str, Any]:
    """跑 collector 后裁掉 metrics, 返 baseline schema v1 字段集合."""
    d = collect(recording_dir, config_dir).to_dict()
    return {
        "schema_version": SCHEMA_VERSION,
        "recording": d["recording"],
        "dock_sn": d["dock_sn"],
        "drone_sn": d["drone_sn"],
        "duration_ms": d["duration_ms"],
        "total_envelopes": d["total_envelopes"],
        "envelope_counts_by_topic_key": d["envelope_counts_by_topic_key"],
        "phase_transitions": d["phase_transitions"],
        "verdicts": d["verdicts"],
        "alert_decisions": d["alert_decisions"],
    }
