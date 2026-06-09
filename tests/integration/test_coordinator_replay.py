"""Phase 5 集成测试: 端到端 ingest→aggregator→engine→coordinator + alerts.jsonl."""

from __future__ import annotations

import json
import pathlib
import textwrap

import pytest

from dock_guard.aggregator import DockAggregator
from dock_guard.config import AppConfig, load_app_config
from dock_guard.coordinator import (
    AlertCoordinator,
    Decision,
    JsonlAlertSink,
    NullAlertSink,
)
from dock_guard.ingest import ReplaySource
from dock_guard.rules import RuleEngine

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def app_config(tmp_path_factory: pytest.TempPathFactory) -> AppConfig:
    repo_config_dir = pathlib.Path(__file__).resolve().parents[2] / "config"
    if not (repo_config_dir / "rules.yaml").exists():
        pytest.skip("repo config not present")
    tmp = tmp_path_factory.mktemp("cfg")
    for name in ("mode_code_map.yaml", "alert_levels.yaml", "enums.yaml", "rules.yaml"):
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
        "MQTT_USERNAME": "x", "MQTT_PASSWORD": "y",
    })


async def test_coordinator_suppresses_warming_up_burst(
    recording: pathlib.Path, app_config: AppConfig
) -> None:
    """WARMING_UP 触发数百次 → coordinator cooldown 应抑制为 1 条 DISPATCHED."""
    src = ReplaySource(recording, speed=0.0)
    agg = DockAggregator(src.dock_sn, app_config)
    eng = RuleEngine(app_config.rules, agg)
    sink = NullAlertSink()
    coord = AlertCoordinator(app_config, sink=sink)

    async for env in src:
        agg.apply(env)
        verdicts = eng.evaluate()
        if verdicts:
            coord.handle_batch(verdicts)

    warmup_records = [r for r in sink.records if r.verdict.code == "WARMING_UP"]
    dispatched = [r for r in warmup_records if r.decision == Decision.DISPATCHED]
    suppressed = [r for r in warmup_records if r.decision == Decision.SUPPRESSED]

    # maint.warming_up cooldown_ms=86400000 → 整个会话只发 1 次
    assert len(dispatched) == 1
    assert len(suppressed) >= 100
    for r in suppressed:
        assert r.gates["cooldown"] == "suppressed_cooldown"


async def test_alerts_jsonl_file_valid(
    recording: pathlib.Path, app_config: AppConfig, tmp_path: pathlib.Path
) -> None:
    alerts_path = tmp_path / "alerts.jsonl"
    src = ReplaySource(recording, speed=0.0)
    agg = DockAggregator(src.dock_sn, app_config)
    eng = RuleEngine(app_config.rules, agg)
    coord = AlertCoordinator(app_config, sink=JsonlAlertSink(alerts_path))

    async for env in src:
        agg.apply(env)
        v = eng.evaluate()
        if v:
            coord.handle_batch(v)
    coord.close()

    assert alerts_path.exists()
    lines = alerts_path.read_text().strip().split("\n")
    assert len(lines) > 0
    for ln in lines:
        d = json.loads(ln)
        assert "ts_ms" in d
        assert "verdict" in d
        assert "decision" in d
        assert "gates" in d
        assert d["decision"] in ("DISPATCHED", "SUPPRESSED")
