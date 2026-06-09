"""Phase 5 单元测试: AlertCoordinator (设计 §6.6 + §6.7)."""

from __future__ import annotations

import json
import pathlib
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any
from unittest.mock import MagicMock

import pytest

from dock_guard.config import (
    AlertLevelsYaml,
    AppConfig,
    CoordinatorParams,
    LevelRouting,
)
from dock_guard.coordinator import AlertCoordinator, Decision, JsonlAlertSink, NullAlertSink
from dock_guard.rules.verdict import Verdict
from dock_guard.types import ChannelKind, Phase, PhaseSource, Severity


def _app_config(default_cd: int = 30000, em_floor: int = 2000,
                burst: int = 10) -> AppConfig:
    al = AlertLevelsYaml(
        version=2,
        level_routing_defaults={
            sev.lower(): LevelRouting(channels=[ChannelKind.PANEL])
            for sev in ("EMERGENCY", "BLOCK", "RETURN", "WARN", "INFO")
        },
        coordinator=CoordinatorParams(
            default_cooldown_ms=default_cd,
            emergency_floor_cooldown_ms=em_floor,
            dedup_window_ms=60000,
            dedup_burst_threshold=burst,
        ),
    )
    cfg = MagicMock(spec=AppConfig)
    cfg.alert_levels = al
    return cfg


def _v(ts: int, code: str = "X", level: Severity = Severity.WARN,
       dock_sn: str = "D1", dedup_key: str | None = None) -> Verdict:
    ctx: Mapping[str, Any] = MappingProxyType({"dock_sn": dock_sn, "drone_sn": "DR1"})
    return Verdict(
        rule_id="r1", level=level, code=code,
        phase_when_fired=Phase.CRUISE,
        phase_source_when_fired=PhaseSource.FLIGHTTASK_STEP_CODE,
        facts={"x": 1}, thresholds={"x": "=1"}, suggested_action="notify",
        context=ctx, ts_ms=ts,
        dedup_key=dedup_key or f"r1#{code}",
    )


class TestCoordinatorBasic:
    def test_first_verdict_dispatched(self) -> None:
        sink = NullAlertSink()
        c = AlertCoordinator(_app_config(), sink=sink)
        r = c.handle(_v(1000))
        assert r.decision == Decision.DISPATCHED
        assert r.gates["cooldown"] == "pass"
        assert r.gates["dedup"] == "pass"
        assert r.gates["mute"] == "pass"
        assert len(sink.records) == 1

    def test_suppressed_still_recorded(self) -> None:
        sink = NullAlertSink()
        c = AlertCoordinator(_app_config(default_cd=30000), sink=sink)
        c.handle(_v(1000))
        r2 = c.handle(_v(2000))
        assert r2.decision == Decision.SUPPRESSED
        assert r2.gates["cooldown"] == "suppressed_cooldown"
        assert len(sink.records) == 2


class TestSorting:
    def test_emergency_processed_first(self) -> None:
        sink = NullAlertSink()
        c = AlertCoordinator(_app_config(), sink=sink)
        verdicts = [
            _v(1000, code="A", level=Severity.WARN),
            _v(1000, code="B", level=Severity.EMERGENCY),
            _v(1000, code="C", level=Severity.RETURN),
        ]
        records = c.handle_batch(verdicts)
        assert [r.verdict.code for r in records] == ["B", "C", "A"]

    def test_same_level_alphabetical(self) -> None:
        sink = NullAlertSink()
        c = AlertCoordinator(_app_config(), sink=sink)
        verdicts = [
            _v(1000, code="Z", level=Severity.WARN),
            _v(1000, code="A", level=Severity.WARN),
        ]
        records = c.handle_batch(verdicts)
        assert [r.verdict.code for r in records] == ["A", "Z"]


class TestMuteSuppresses:
    def test_dock_mute_below_threshold(self) -> None:
        sink = NullAlertSink()
        c = AlertCoordinator(_app_config(), sink=sink)
        c.mute.set_dock_mute("D1", enabled=True,
                             min_severity_to_send=Severity.EMERGENCY,
                             duration_s=600, now_ms=1000)
        r = c.handle(_v(1500, level=Severity.WARN))
        assert r.decision == Decision.SUPPRESSED
        assert r.gates["mute"] == "muted_dock"


class TestAlertRecordSchema:
    def test_to_dict_has_all_required_fields(self) -> None:
        c = AlertCoordinator(_app_config())
        r = c.handle(_v(1000))
        d = r.to_dict()
        for key in ("ts_ms", "dock_sn", "drone_sn", "verdict_ref",
                    "verdict", "suggested_action", "decision", "gates", "channels"):
            assert key in d
        for key in ("level", "code", "phase_when_fired", "phase_source",
                    "facts", "thresholds"):
            assert key in d["verdict"]

    def test_verdict_ref_format(self) -> None:
        c = AlertCoordinator(_app_config())
        r = c.handle(_v(1234567000))
        assert r.to_dict()["verdict_ref"] == "r1#1234567000"


class TestJsonlAlertSink:
    def test_appends_and_jsonl_parsable(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "alerts.jsonl"
        sink = JsonlAlertSink(path)
        c = AlertCoordinator(_app_config(), sink=sink)
        c.handle(_v(1000, code="A"))
        c.handle(_v(60000, code="B"))
        sink.close()

        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2
        d1 = json.loads(lines[0])
        d2 = json.loads(lines[1])
        assert d1["verdict"]["code"] == "A"
        assert d2["verdict"]["code"] == "B"
        assert d1["decision"] == "DISPATCHED"

    @pytest.mark.parametrize("nested_path", ["a/b/c/alerts.jsonl"])
    def test_creates_parent_dirs(self, tmp_path: pathlib.Path, nested_path: str) -> None:
        path = tmp_path / nested_path
        sink = JsonlAlertSink(path)
        sink.close()
        assert path.exists()
