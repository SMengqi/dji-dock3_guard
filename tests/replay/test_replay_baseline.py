"""Stage 3-D B3: 回放基线回归测试 (设计 §12.4).

跑 sim 录制 -> 与提交的 tests/replay/baselines/<recording>.json 对比.
任何 rules.yaml / aggregator / engine / ingest / coordinator 改动都
会让基线 diff 不为零, PR 必须显式 regen baseline 才能合并.

regen 命令: python scripts/regen_replay_baseline.py
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from tests.replay._helpers import run_replay_collect, stage_config_dir

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BASELINES_DIR = REPO_ROOT / "tests" / "replay" / "baselines"


@pytest.fixture(scope="module")
def baseline_path(recording: pathlib.Path) -> pathlib.Path:
    path = BASELINES_DIR / f"{recording.name}.json"
    if not path.exists():
        pytest.skip(
            f"baseline 缺失: {path.relative_to(REPO_ROOT)}\n"
            "首次生成或被删了, 跑: python scripts/regen_replay_baseline.py"
        )
    return path


@pytest.fixture(scope="module")
def current(recording: pathlib.Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """跑一次 replay, 得出当前 pipeline 输出 dict."""
    tmp = tmp_path_factory.mktemp("replay_baseline_cfg")
    stage_config_dir(tmp, REPO_ROOT / "config")
    return run_replay_collect(recording, tmp)


@pytest.fixture(scope="module")
def baseline(baseline_path: pathlib.Path) -> dict[str, Any]:
    return json.loads(baseline_path.read_text(encoding="utf-8"))


class TestReplayBaseline:
    def test_schema_version_match(
        self, current: dict[str, Any], baseline: dict[str, Any]
    ) -> None:
        assert current["schema_version"] == baseline["schema_version"], (
            f"baseline schema_version 不一致: 当前 {current['schema_version']} "
            f"vs baseline {baseline['schema_version']}"
        )

    def test_envelope_totals_match(
        self, current: dict[str, Any], baseline: dict[str, Any]
    ) -> None:
        assert current["total_envelopes"] == baseline["total_envelopes"]
        assert current["duration_ms"] == baseline["duration_ms"]
        assert current["dock_sn"] == baseline["dock_sn"]
        assert current["drone_sn"] == baseline["drone_sn"]

    def test_envelope_counts_by_topic_match(
        self, current: dict[str, Any], baseline: dict[str, Any]
    ) -> None:
        cur = current["envelope_counts_by_topic_key"]
        base = baseline["envelope_counts_by_topic_key"]
        assert cur == base, _dict_diff_msg(cur, base, "envelope_counts_by_topic_key")

    def test_phase_transitions_match(
        self, current: dict[str, Any], baseline: dict[str, Any]
    ) -> None:
        cur = current["phase_transitions"]
        base = baseline["phase_transitions"]
        assert len(cur) == len(base), (
            f"phase_transitions 数量不一致: 当前 {len(cur)} vs baseline {len(base)}"
        )
        for i, (c, b) in enumerate(zip(cur, base, strict=False)):
            assert c == b, (
                f"phase_transitions[{i}] 不一致:\n"
                f"  当前:    {c}\n"
                f"  baseline: {b}"
            )

    def test_verdicts_match(
        self, current: dict[str, Any], baseline: dict[str, Any]
    ) -> None:
        cur = current["verdicts"]
        base = baseline["verdicts"]
        assert len(cur) == len(base), (
            f"verdicts 数量不一致: 当前 {len(cur)} vs baseline {len(base)}\n"
            "如果是有意改 rules/aggregator: 跑 python scripts/regen_replay_baseline.py"
        )
        for i, (c, b) in enumerate(zip(cur, base, strict=False)):
            assert c == b, (
                f"verdicts[{i}] 不一致:\n"
                f"  当前:    {c}\n"
                f"  baseline: {b}"
            )

    def test_alert_decisions_match(
        self, current: dict[str, Any], baseline: dict[str, Any]
    ) -> None:
        cur = current["alert_decisions"]
        base = baseline["alert_decisions"]
        assert len(cur) == len(base), (
            f"alert_decisions 数量不一致: 当前 {len(cur)} vs baseline {len(base)}\n"
            "如果是有意改 coordinator (cooldown/dedup/mute): "
            "跑 python scripts/regen_replay_baseline.py"
        )
        for i, (c, b) in enumerate(zip(cur, base, strict=False)):
            assert c == b, (
                f"alert_decisions[{i}] 不一致:\n"
                f"  当前:    {c}\n"
                f"  baseline: {b}"
            )


def _dict_diff_msg(cur: dict, base: dict, label: str) -> str:
    only_cur = set(cur) - set(base)
    only_base = set(base) - set(cur)
    diff_keys = [k for k in cur if k in base and cur[k] != base[k]]
    parts = [f"{label} 不一致:"]
    if only_cur:
        parts.append(f"  当前新增 key: {sorted(only_cur)}")
    if only_base:
        parts.append(f"  baseline 缺少 key (被删): {sorted(only_base)}")
    if diff_keys:
        parts.append("  值不同:")
        for k in diff_keys[:10]:
            parts.append(f"    {k}: 当前={cur[k]!r} baseline={base[k]!r}")
    return "\n".join(parts)
