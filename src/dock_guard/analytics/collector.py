"""Stage 4-E: 跑流水线 + 提取指标 -> FlightReport (设计 §4 §5).

复用 Stage 3-D B3 的 tests/replay/_helpers 同套结构 (ReplaySource ->
DockAggregator -> RuleEngine -> AlertCoordinator), 在主循环里多采样
peak_wind_gust_30s / min_battery 并算 phase 间隔.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
from collections import Counter
from collections.abc import Mapping
from typing import Any

from dock_guard.aggregator import DockAggregator
from dock_guard.analytics.models import (
    SCHEMA_VERSION,
    FlightMetrics,
    FlightReport,
)
from dock_guard.config import load_app_config
from dock_guard.coordinator import AlertCoordinator, NullAlertSink
from dock_guard.ingest import ReplaySource
from dock_guard.rules import RuleEngine


def collect(
    recording_dir: pathlib.Path,
    config_dir: pathlib.Path,
    *,
    env: Mapping[str, str] | None = None,
) -> FlightReport:
    """跑离线分析流水线 -> FlightReport.

    env 用于展开 yaml 配置里的 ${VAR} 占位符 (跟 load_app_config 同口径).
    不传 (None) -> 默认用 os.environ; 生产 CLI 通过 __main__.load_dotenv()
    把 .env 注入 os.environ, 这样 dingtalk_robots.yaml 的 ${DINGTALK_*} 等
    占位符能正确展开 (即便离线分析不发钉钉, load_app_config 仍要展开 yaml).
    显式传入 (例: tests/replay/_helpers.py 的 _FAKE_ENV) 时用传入值,
    跟生产 env 隔离.
    """
    return asyncio.run(_collect_async(recording_dir, config_dir, env))


async def _collect_async(
    recording_dir: pathlib.Path,
    config_dir: pathlib.Path,
    env: Mapping[str, str] | None,
) -> FlightReport:
    effective_env = env if env is not None else dict(os.environ)
    cfg = load_app_config(config_dir, env=effective_env)
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

    peak_wind: float | None = None
    peak_wind_at: int | None = None
    min_batt: int | None = None
    min_batt_at: int | None = None
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

        frame = agg.latest_facts()
        if frame is not None:
            wind = frame.facts.get("wind_gust_max_30s")
            if isinstance(wind, (int, float)):
                w = float(wind)
                if peak_wind is None or w > peak_wind:
                    peak_wind, peak_wind_at = w, env.recv_ts_ms
            batt = frame.facts.get("battery_capacity_percent")
            if isinstance(batt, int) and 0 <= batt <= 100:
                if min_batt is None or batt < min_batt:
                    min_batt, min_batt_at = batt, env.recv_ts_ms

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

    started_at = first_ts or 0
    ended_at = last_ts or started_at
    duration_ms = ended_at - started_at

    durations = _phase_durations(phase_transitions, started_at, ended_at)
    longest_offline = _longest_offline(phase_transitions, started_at, ended_at)
    flight_dur = max(
        sum(durations.values())
        - durations.get("OFFLINE", 0) - durations.get("IDLE", 0),
        0,
    )

    decisions = Counter(d["decision"] for d in alert_decisions)
    codes = Counter(v["code"] for v in verdicts)

    metrics = FlightMetrics(
        peak_wind_gust_30s=peak_wind,
        peak_wind_gust_30s_at_ms=peak_wind_at,
        min_battery_percent=min_batt,
        min_battery_percent_at_ms=min_batt_at,
        longest_offline_ms=longest_offline,
        flight_duration_ms=flight_dur,
        total_verdicts=len(verdicts),
        total_dispatched=decisions.get("DISPATCHED", 0),
        total_suppressed=decisions.get("SUPPRESSED", 0),
        verdicts_by_code=dict(codes),
    )

    return FlightReport(
        schema_version=SCHEMA_VERSION,
        recording=recording_dir.name,
        dock_sn=src.dock_sn,
        drone_sn=src.drone_sn,
        started_at_ms=started_at,
        ended_at_ms=ended_at,
        duration_ms=duration_ms,
        total_envelopes=total,
        envelope_counts_by_topic_key=dict(sorted(envelope_counts.items())),
        phase_transitions=phase_transitions,
        verdicts=verdicts,
        alert_decisions=alert_decisions,
        metrics=metrics,
    )


def _phase_durations(
    transitions: list[dict[str, Any]], started_at: int, ended_at: int
) -> dict[str, int]:
    out: dict[str, int] = {}
    if not transitions:
        return out
    out[transitions[0]["phase_from"]] = transitions[0]["ts_ms"] - started_at
    for i in range(len(transitions) - 1):
        cur, nxt = transitions[i], transitions[i + 1]
        out[cur["phase_to"]] = out.get(cur["phase_to"], 0) + (nxt["ts_ms"] - cur["ts_ms"])
    last = transitions[-1]
    out[last["phase_to"]] = out.get(last["phase_to"], 0) + (ended_at - last["ts_ms"])
    return out


def _longest_offline(
    transitions: list[dict[str, Any]], started_at: int, ended_at: int
) -> int:
    if not transitions:
        return 0
    intervals: list[int] = []
    start: int | None = (
        started_at if transitions[0]["phase_from"] == "OFFLINE" else None
    )
    for tr in transitions:
        if tr["phase_to"] == "OFFLINE":
            start = tr["ts_ms"]
        elif tr["phase_from"] == "OFFLINE" and start is not None:
            intervals.append(tr["ts_ms"] - start)
            start = None
    if start is not None:
        intervals.append(ended_at - start)
    return max(intervals, default=0)
