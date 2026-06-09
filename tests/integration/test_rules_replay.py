"""Phase 4 集成测试: 端到端 ingest→aggregator→engine 跑真实样本."""

from __future__ import annotations

import pathlib
import textwrap
from collections import Counter

import pytest

from dock_guard.aggregator import DockAggregator
from dock_guard.config import AppConfig, load_app_config
from dock_guard.ingest import ReplaySource
from dock_guard.rules import RuleEngine
from dock_guard.types import Severity

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


async def test_clean_sample_no_dangerous_verdicts(
    recording: pathlib.Path, app_config: AppConfig
) -> None:
    src = ReplaySource(recording, speed=0.0)
    agg = DockAggregator(src.dock_sn, app_config)
    eng = RuleEngine(app_config.rules, agg)

    verdicts = []
    async for env in src:
        agg.apply(env)
        verdicts.extend(eng.evaluate())

    severe = [v for v in verdicts if v.level >= Severity.RETURN]
    assert severe == [], \
        f"clean sample 不应有 BLOCK/RETURN/EMERGENCY: {[(v.code, v.level.name) for v in severe]}"


async def test_warming_up_verdict_fires_on_startup(
    recording: pathlib.Path, app_config: AppConfig
) -> None:
    src = ReplaySource(recording, speed=0.0)
    agg = DockAggregator(src.dock_sn, app_config)
    eng = RuleEngine(app_config.rules, agg)

    verdicts = []
    async for env in src:
        agg.apply(env)
        verdicts.extend(eng.evaluate())

    warmup_verdicts = [v for v in verdicts if v.code == "WARMING_UP"]
    assert len(warmup_verdicts) >= 1
    assert warmup_verdicts[0].level == Severity.INFO


async def test_verdict_distribution(
    recording: pathlib.Path, app_config: AppConfig
) -> None:
    src = ReplaySource(recording, speed=0.0)
    agg = DockAggregator(src.dock_sn, app_config)
    eng = RuleEngine(app_config.rules, agg)

    verdicts = []
    async for env in src:
        agg.apply(env)
        verdicts.extend(eng.evaluate())

    by_code: Counter[str] = Counter(v.code for v in verdicts)
    assert "WARMING_UP" in by_code
    assert "PREFLIGHT_WIND_EXCEEDED" not in by_code
    assert "PREFLIGHT_HEAVY_RAIN" not in by_code
    print()
    print(f"verdict distribution on clean sample: {dict(by_code)}")


async def test_verdict_has_dedup_key_and_context(
    recording: pathlib.Path, app_config: AppConfig
) -> None:
    src = ReplaySource(recording, speed=0.0)
    agg = DockAggregator(src.dock_sn, app_config)
    eng = RuleEngine(app_config.rules, agg)

    verdicts = []
    async for env in src:
        agg.apply(env)
        verdicts.extend(eng.evaluate())
        if verdicts:
            break

    assert verdicts
    v = verdicts[0]
    assert v.dedup_key.startswith(v.rule_id + "#")
    assert v.context["dock_sn"] == "8UUXN7N00A0GAA"
