"""Phase 3 集成测试: DockAggregator 跑真实样本, 验证 phase 时间线."""

from __future__ import annotations

import pathlib
import textwrap

import pytest

from dock_guard.aggregator import DockAggregator
from dock_guard.aggregator.facts import F
from dock_guard.config import AppConfig, load_app_config
from dock_guard.ingest import ReplaySource
from dock_guard.types import Phase, PhaseSource

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def app_config(tmp_path_factory: pytest.TempPathFactory) -> AppConfig:
    repo_config_dir = pathlib.Path(__file__).resolve().parents[2] / "config"
    if not (repo_config_dir / "mode_code_map.yaml").exists():
        pytest.skip("repo config not present")
    tmp = tmp_path_factory.mktemp("cfg")
    for name in ("mode_code_map.yaml", "alert_levels.yaml", "enums.yaml"):
        (tmp / name).symlink_to(repo_config_dir / name)
    (tmp / "runtime.yaml").write_text(textwrap.dedent("""
        schema_version: 1
        mqtt:
          broker_url:  ${MQTT_BROKER_URL}
          username:    ${MQTT_USERNAME}
          password:    ${MQTT_PASSWORD}
        subscriptions:
          - dock_sn: 8UUXN7N00A0GAA
            enabled: true
    """))
    return load_app_config(tmp, env={
        "MQTT_BROKER_URL": "ssl://test:8883",
        "MQTT_USERNAME": "x",
        "MQTT_PASSWORD": "y",
    }, with_rules=False)


async def test_replay_sample_produces_phase_timeline(
    recording: pathlib.Path, app_config: AppConfig
) -> None:
    src = ReplaySource(recording, speed=0.0)
    agg = DockAggregator(src.dock_sn, app_config)

    transitions = []
    async for env in src:
        agg.apply(env)
        transitions.extend(agg.drain_phase_transitions())

    phases_seen = [t.phase_to for t in transitions]
    assert Phase.OFFLINE in {t.phase_from for t in transitions}

    # 样本里飞行器 mode_code 集合 {0,1,3,4,5,9,10,17} 应当触达
    # CRUISE / RTH / LANDING (具体 phase 取决于二维表)
    assert Phase.CRUISE in phases_seen, f"expected CRUISE in {phases_seen}"
    assert Phase.RTH in phases_seen, f"expected RTH in {phases_seen}"
    assert Phase.LANDING in phases_seen, f"expected LANDING in {phases_seen}"


async def test_facts_snapshot_has_core_keys(
    recording: pathlib.Path, app_config: AppConfig
) -> None:
    src = ReplaySource(recording, speed=0.0)
    agg = DockAggregator(src.dock_sn, app_config)
    async for env in src:
        agg.apply(env)

    latest = agg.latest_facts()
    assert latest is not None
    keys = latest.facts.keys()

    assert F.PHASE in keys
    assert F.PHASE_SOURCE in keys
    assert F.DOCK_SN in keys

    assert F.COVER_STATE in keys
    assert F.RAINFALL in keys
    assert F.DOCK_INSIDE_TEMPERATURE in keys
    assert F.WIND_SPEED_DOCK in keys

    assert F.MODE_CODE in keys
    assert F.HEIGHT in keys
    assert F.BATTERY_CAPACITY_PERCENT in keys
    assert F.BATTERY_RETURN_HOME_POWER in keys
    assert F.RTK_FIXED in keys


async def test_facts_ring_populated(
    recording: pathlib.Path, app_config: AppConfig
) -> None:
    src = ReplaySource(recording, speed=0.0)
    agg = DockAggregator(src.dock_sn, app_config)
    async for env in src:
        agg.apply(env)
    assert len(agg.facts_ring) > 0
    assert agg.facts_ring.latest() is not None


async def test_phase_transitions_have_monotonic_ts(
    recording: pathlib.Path, app_config: AppConfig
) -> None:
    src = ReplaySource(recording, speed=0.0)
    agg = DockAggregator(src.dock_sn, app_config)
    transitions = []
    async for env in src:
        agg.apply(env)
        transitions.extend(agg.drain_phase_transitions())

    last_ts = 0
    for tr in transitions:
        assert tr.ts_ms >= last_ts
        last_ts = tr.ts_ms


async def test_aggregator_drone_sn_discovered(
    recording: pathlib.Path, app_config: AppConfig
) -> None:
    src = ReplaySource(recording, speed=0.0)
    agg = DockAggregator(src.dock_sn, app_config)
    assert agg.drone_sn is None
    async for env in src:
        agg.apply(env)
        if agg.drone_sn is not None:
            break
    assert agg.drone_sn == "1581F8HGX257Q00A0PSH"


async def test_phase_source_changes_when_dock_task_stops(
    app_config: AppConfig
) -> None:
    """注入 envelope: dock 任务步进沉默 > 5s + drone 在天上 → phase_source 切到 mode_code."""
    from dock_guard.ingest.source import Envelope
    from dock_guard.types import TopicKey

    agg = DockAggregator("TEST_DOCK", app_config)

    def env(ts_ms: int, topic_key: TopicKey, payload: dict) -> Envelope:
        is_drone = topic_key in (TopicKey.DRONE_OSD,)
        return Envelope(
            recv_ts_ms=ts_ms, dji_ts_ms=ts_ms, direction="up",
            topic="x", payload=payload,
            topic_key=topic_key,
            dock_sn="TEST_DOCK",
            drone_sn="TEST_DRONE" if is_drone else None,
        )

    agg.apply(env(1000, TopicKey.DOCK_OSD, {"data": {"flighttask_step_code": 1}}))
    agg.apply(env(1500, TopicKey.DOCK_EVENTS,
                  {"method": "flighttask_progress", "data": {}}))
    agg.apply(env(2000, TopicKey.DRONE_OSD,
                  {"data": {"mode_code": 5, "height": 50, "vertical_speed": 0}}))
    _ = list(agg.drain_phase_transitions())
    assert agg.current_phase == Phase.CRUISE
    assert agg.current_phase_source == PhaseSource.FLIGHTTASK_STEP_CODE

    # 时间推进, dock OSD 仍喂 (避免 OFFLINE), flighttask_progress 不再
    agg.apply(env(7000, TopicKey.DOCK_OSD, {"data": {}}))
    agg.apply(env(12000, TopicKey.DRONE_OSD,
                  {"data": {"mode_code": 5, "height": 50, "vertical_speed": 0}}))
    transitions_b = list(agg.drain_phase_transitions())

    src_changes = [t for t in transitions_b if t.phase_source_to == PhaseSource.MODE_CODE]
    assert src_changes, f"expected source change to MODE_CODE, got {transitions_b}"
    assert agg.current_phase == Phase.CRUISE
    assert agg.current_phase_source == PhaseSource.MODE_CODE
