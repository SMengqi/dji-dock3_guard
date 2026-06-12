"""Stage 3-D B3: 共享给 regen 脚本和 baseline 测试的 replay 跑流水线 helper.

把整段 sim 录制喂进 ingest -> aggregator -> rules -> coordinator, 收齐
phase_transitions / verdicts / alert_decisions / envelope_counts, 返回
一份 stable JSON-able dict (baseline 文件存放的就是这玩意).

Stable 字段口径:
- 只保留**确定性**字段; ts_ms / dedup_key 来自录制 recv_ts_ms, 确定性.
- facts / thresholds 不入 baseline (浮点细节 + 体积爆), Verdict 自身的
  rule_id / code / level / phase_when_fired 已经足够回归覆盖.
- AlertRecord.channels 不入 baseline (依赖 dingtalk 配置不属 replay 范畴).
"""

from __future__ import annotations

import asyncio
import pathlib
import textwrap
from collections import Counter
from typing import Any

from dock_guard.aggregator import DockAggregator
from dock_guard.config import load_app_config
from dock_guard.coordinator import AlertCoordinator, NullAlertSink
from dock_guard.ingest import ReplaySource
from dock_guard.rules import RuleEngine

SCHEMA_VERSION = 1


_FAKE_ENV = {
    "MQTT_BROKER_URL": "tcp://baseline-test:1883",
    "MQTT_USERNAME": "x",
    "MQTT_PASSWORD": "x",
    "MQTT_DOCK_SN": "8UUXN7N00A0GAA",
    "ADMIN_TOKEN": "baseline-test-token",
}


def stage_config_dir(dst: pathlib.Path, repo_config_dir: pathlib.Path) -> None:
    """合成最小 runtime.yaml + 复用仓库 mode_code_map/alert_levels/enums/rules.

    供调用者准备一个临时 config_dir (tmp_path) 喂给 _collect.
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


async def _collect(recording_dir: pathlib.Path, config_dir: pathlib.Path) -> dict[str, Any]:
    cfg = load_app_config(config_dir, env=_FAKE_ENV)
    src = ReplaySource(recording_dir, speed=0)

    agg = DockAggregator(src.dock_sn, cfg)
    engine = RuleEngine(cfg.rules, agg) if cfg.rules is not None else None
    coordinator = (
        AlertCoordinator(cfg, sink=NullAlertSink()) if engine is not None else None
    )

    envelope_counts: Counter[str] = Counter()
    phase_transitions: list[dict[str, Any]] = []
    verdicts: list[dict[str, Any]] = []
    alert_decisions: list[dict[str, Any]] = []

    first_ts: int | None = None
    last_ts: int | None = None
    total = 0

    async for env in src:
        total += 1
        envelope_counts[env.topic_key.value] += 1
        if first_ts is None:
            first_ts = env.recv_ts_ms
        last_ts = env.recv_ts_ms
        agg.apply(env)
        for tr in agg.drain_phase_transitions():
            phase_transitions.append({
                "ts_ms": tr.ts_ms,
                "phase_from": tr.phase_from.value,
                "phase_to": tr.phase_to.value,
                "phase_source_from": tr.phase_source_from.value,
                "phase_source_to": tr.phase_source_to.value,
                "reason": tr.reason,
                "mode_code": tr.mode_code,
                "drone_in_dock": tr.drone_in_dock,
                "warnings": list(tr.warnings),
            })
        if engine is not None and coordinator is not None:
            batch = engine.evaluate()
            for v in batch:
                verdicts.append({
                    "ts_ms": v.ts_ms,
                    "rule_id": v.rule_id,
                    "code": v.code,
                    "level": v.level.name,
                    "phase_when_fired": v.phase_when_fired.value,
                    "phase_source_when_fired": v.phase_source_when_fired.value,
                    "suggested_action": v.suggested_action,
                    "dedup_key": v.dedup_key,
                })
            for rec in coordinator.handle_batch(batch):
                alert_decisions.append({
                    "ts_ms": rec.ts_ms,
                    "code": rec.verdict.code,
                    "level": rec.verdict.level.name,
                    "decision": rec.decision.value,
                    "gates": dict(rec.gates),
                })

    if coordinator is not None:
        coordinator.close()
    await src.close()

    duration_ms = (last_ts - first_ts) if (first_ts and last_ts) else 0

    return {
        "schema_version": SCHEMA_VERSION,
        "recording": recording_dir.name,
        "dock_sn": src.dock_sn,
        "drone_sn": src.drone_sn,
        "duration_ms": duration_ms,
        "total_envelopes": total,
        "envelope_counts_by_topic_key": dict(sorted(envelope_counts.items())),
        "phase_transitions": phase_transitions,
        "verdicts": verdicts,
        "alert_decisions": alert_decisions,
    }


def run_replay_collect(
    recording_dir: pathlib.Path,
    config_dir: pathlib.Path,
) -> dict[str, Any]:
    """同步包装. recording_dir 录制目录, config_dir 已经 stage 好的 config."""
    return asyncio.run(_collect(recording_dir, config_dir))
