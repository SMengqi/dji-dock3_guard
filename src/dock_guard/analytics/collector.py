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
    BatterySample,
    FlightMetrics,
    FlightReport,
    FlightSample,
    HsiSample,
    LinkSample,
    StickSample,
)
from dock_guard.config import load_app_config
from dock_guard.coordinator import AlertCoordinator, NullAlertSink
from dock_guard.ingest import ReplaySource
from dock_guard.rules import RuleEngine
from dock_guard.types import TopicKey

SAMPLE_INTERVAL_MS = 10_000   # Stage 5-F: 每 10s 采一次 battery_samples


def _facts_float(facts: Mapping[str, Any], key: str) -> float | None:
    v = facts.get(key)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _facts_int(facts: Mapping[str, Any], key: str) -> int | None:
    v = facts.get(key)
    return int(v) if isinstance(v, int) and not isinstance(v, bool) else None


def _osd_float(osd: Any, key: str) -> float | None:
    if not isinstance(osd, Mapping):
        return None
    v = osd.get(key)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _as_int(v: Any) -> int | None:
    return int(v) if isinstance(v, int) and not isinstance(v, bool) else None


def _as_bool(v: Any) -> bool | None:
    return v if isinstance(v, bool) else None


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
    src = ReplaySource(recording_dir, speed=0, drop_drc=False)

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

    # Stage 5-F: 10s 间隔的 battery_samples 时序
    battery_samples: list[BatterySample] = []
    flight_samples: list[FlightSample] = []
    hsi_samples: list[HsiSample] = []
    stick_samples: list[StickSample] = []
    link_samples: list[LinkSample] = []
    transfer_events: list[dict] = []
    hms_events: list[dict] = []
    next_sample_rel_ms = 0
    # 风向计数 (10s 一格 -> 秒数 = count * 10)
    wind_direction_counts: dict[str, int] = {}

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
            # Stage 5-F: 每 10s 采样 battery_samples (要 battery + height + wind 全就绪)
            if first_ts is not None:
                rel_ms = env.recv_ts_ms - first_ts
                if rel_ms >= next_sample_rel_ms:
                    height = frame.facts.get("height")
                    if (isinstance(batt, int) and 0 <= batt <= 100
                            and isinstance(height, (int, float))
                            and isinstance(wind, (int, float))):
                        wd = frame.facts.get("wind_direction")
                        wd_int = wd if isinstance(wd, int) and 1 <= wd <= 8 else None
                        hs = frame.facts.get("horizontal_speed")
                        vs = frame.facts.get("vertical_speed")
                        hs_f = float(hs) if isinstance(hs, (int, float)) else None
                        vs_f = float(vs) if isinstance(vs, (int, float)) else None
                        battery_samples.append(BatterySample(
                            rel_ms=rel_ms, percent=batt,
                            height_m=float(height), wind_ms=float(wind),
                            wind_direction=wd_int,
                            horizontal_speed_ms=hs_f, vertical_speed_ms=vs_f,
                        ))
                        if wd_int is not None:
                            key = str(wd_int)
                            wind_direction_counts[key] = (
                                wind_direction_counts.get(key, 0) + 1
                            )
                        next_sample_rel_ms += SAMPLE_INTERVAL_MS

        if (frame is not None and first_ts is not None
                and env.topic_key == TopicKey.DRONE_OSD):
            f = frame.facts
            fixed = f.get("rtk_fixed")
            drc = f.get("drc_state")
            osd = env.payload.get("data") if isinstance(env.payload, dict) else None
            flight_samples.append(FlightSample(
                rel_ms=env.recv_ts_ms - first_ts,
                height_m=_facts_float(f, "height"),
                vertical_speed_ms=_facts_float(f, "vertical_speed"),
                horizontal_speed_ms=_facts_float(f, "horizontal_speed"),
                attitude_head=_facts_float(f, "attitude_head"),
                attitude_pitch=_facts_float(f, "attitude_pitch"),
                attitude_roll=_facts_float(f, "attitude_roll"),
                gps_number=_facts_int(f, "gps_number"),
                rtk_number=_facts_int(f, "rtk_number"),
                is_fixed=bool(fixed) if isinstance(fixed, bool) else None,
                drc_state=str(drc) if drc is not None else None,
                latitude=_osd_float(osd, "latitude"),
                longitude=_osd_float(osd, "longitude"),
            ))

        if (env.topic_key == TopicKey.DOCK_DRC_UP
                and first_ts is not None
                and isinstance(env.payload, dict)
                and env.payload.get("method") == "hsi_info_push"):
            data = env.payload.get("data")
            if isinstance(data, dict):
                elev = frame.facts.get("elevation") if frame is not None else None
                around = data.get("around_distances")
                hsi_samples.append(HsiSample(
                    rel_ms=env.recv_ts_ms - first_ts,
                    down_distance_mm=_as_int(data.get("down_distance")),
                    down_enable=_as_bool(data.get("down_enable")),
                    down_work=_as_bool(data.get("down_work")),
                    up_distance_mm=_as_int(data.get("up_distance")),
                    up_enable=_as_bool(data.get("up_enable")),
                    up_work=_as_bool(data.get("up_work")),
                    around_distances_mm=(
                        [int(x) for x in around
                         if isinstance(x, (int, float)) and not isinstance(x, bool)] or None
                        if isinstance(around, list) else None
                    ),
                    elevation_m=(
                        float(elev) if isinstance(elev, (int, float))
                        and not isinstance(elev, bool) else None
                    ),
                ))

        if (env.topic_key == TopicKey.DOCK_DRC_DOWN
                and first_ts is not None
                and isinstance(env.payload, dict)
                and env.payload.get("method") == "stick_control"):
            data = env.payload.get("data")
            if isinstance(data, dict):
                stick_samples.append(StickSample(
                    rel_ms=env.recv_ts_ms - first_ts,
                    roll=_as_int(data.get("roll")),
                    pitch=_as_int(data.get("pitch")),
                    yaw=_as_int(data.get("yaw")),
                    throttle=_as_int(data.get("throttle")),
                ))

        if (env.topic_key == TopicKey.DOCK_DRC_UP
                and first_ts is not None
                and isinstance(env.payload, dict)
                and env.payload.get("method") == "drc_geo_connect_info_push"):
            wl = (env.payload.get("data") or {}).get("wireless_link")
            if isinstance(wl, dict):
                link_samples.append(LinkSample(
                    rel_ms=env.recv_ts_ms - first_ts,
                    sdr_quality=_as_int(wl.get("sdr_quality")),
                    fourg_quality=_as_int(wl.get("4g_quality")),
                ))

        if (env.topic_key == TopicKey.DOCK_SERVICES
                and first_ts is not None
                and isinstance(env.payload, dict)):
            method = env.payload.get("method")
            data = env.payload.get("data")
            if method in ("fly_to_point", "takeoff_to_point") and isinstance(data, dict):
                if method == "fly_to_point":
                    pts = data.get("points")
                    th = (pts[-1].get("height")
                          if isinstance(pts, list) and pts and isinstance(pts[-1], dict)
                          else None)
                    ttype = "fly_to"
                else:
                    th = data.get("target_height")
                    ttype = "takeoff"
                transfer_events.append({
                    "rel_ms": env.recv_ts_ms - first_ts,
                    "type": ttype,
                    "target_height": (float(th)
                                      if isinstance(th, (int, float)) and not isinstance(th, bool)
                                      else None),
                })

        if (env.topic_key in (TopicKey.DRONE_EVENTS, TopicKey.DOCK_EVENTS)
                and first_ts is not None
                and isinstance(env.payload, dict)
                and env.payload.get("method") == "hms"):
            data = env.payload.get("data")
            alist = data.get("list") if isinstance(data, dict) else None
            if isinstance(alist, list):
                device = "drone" if env.topic_key == TopicKey.DRONE_EVENTS else "dock"
                rel = env.recv_ts_ms - first_ts
                for item in alist:
                    if not isinstance(item, dict):
                        continue
                    lvl = _as_int(item.get("level"))
                    mod = _as_int(item.get("module"))
                    hms_events.append({
                        "rel_ms": rel,
                        "code": str(item.get("code", "")),
                        "level": lvl if lvl is not None else -1,
                        "module": mod if mod is not None else -1,
                        "device": device,
                    })

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
        wind_direction_seconds={
            k: v * (SAMPLE_INTERVAL_MS // 1000)
            for k, v in wind_direction_counts.items()
        },
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
        battery_samples=battery_samples,
        flight_samples=flight_samples,
        hsi_samples=hsi_samples,
        stick_samples=stick_samples,
        link_samples=link_samples,
        transfer_events=transfer_events,
        hms_events=hms_events,
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
