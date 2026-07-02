#!/usr/bin/env python3
"""regen_replay_baseline — Stage 3-D B3 baseline 重生成器.

把 sim 录制喂进 dock_guard 流水线, 把 phase_transitions / verdicts /
alert_decisions / envelope_counts 序列化成 baseline JSON 写盘.

用法:
    python scripts/regen_replay_baseline.py [录制目录]

录制目录默认: ../sim_dji_cloud_service/sim_dji_cloud/recordings/8UUXN7N00A0GAA_20260605-165145/

何时跑:
- 改了 rules.yaml / aggregator / engine / ingest 的 PR 必须跑一次.
- 跑完 commit 新 baseline + PR 描述里说"基线变化原因".
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from tests.replay._helpers import run_replay_collect, stage_config_dir  # noqa: E402

_DEFAULT_RECORDING = (
    REPO_ROOT.parent
    / "sim_dji_cloud_service" / "sim_dji_cloud" / "recordings"
    / "8UUXN7N00A0GAA_20260605-165145"
)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "recording",
        type=pathlib.Path, nargs="?", default=_DEFAULT_RECORDING,
        help=f"录制目录, 默认 {_DEFAULT_RECORDING.name}",
    )
    p.add_argument(
        "--baselines-dir",
        type=pathlib.Path, default=REPO_ROOT / "tests" / "replay" / "baselines",
        help="baseline 输出目录, 默认 tests/replay/baselines/",
    )
    args = p.parse_args()

    recording = args.recording.resolve()
    if not recording.exists():
        print(f"录制目录不存在: {recording}", file=sys.stderr)
        return 2

    config_repo = REPO_ROOT / "config"
    if not (config_repo / "mode_code_map.yaml").exists():
        print(f"config 目录缺关键 yaml: {config_repo}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as tmp:
        tmp_config = pathlib.Path(tmp)
        stage_config_dir(tmp_config, config_repo)
        baseline = run_replay_collect(recording, tmp_config)

    out_path = args.baselines_dir / f"{recording.name}.json"
    args.baselines_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    print(f"baseline 已写入: {out_path}")
    print(f"  envelopes  : {baseline['total_envelopes']}")
    print(f"  duration_ms: {baseline['duration_ms']}")
    print(f"  transitions: {len(baseline['phase_transitions'])}")
    print(f"  verdicts   : {len(baseline['verdicts'])}")
    print(f"  decisions  : {len(baseline['alert_decisions'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
