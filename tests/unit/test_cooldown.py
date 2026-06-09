"""Phase 5 单元测试: CooldownGate (设计 §6.3)."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from dock_guard.config import CoordinatorParams
from dock_guard.coordinator.cooldown import CooldownGate
from dock_guard.rules.verdict import Verdict
from dock_guard.types import Phase, PhaseSource, Severity


def _v(ts: int, code: str = "X", level: Severity = Severity.RETURN,
       dock_sn: str = "DOCK1") -> Verdict:
    ctx: Mapping[str, Any] = MappingProxyType({"dock_sn": dock_sn})
    return Verdict(
        rule_id="r1", level=level, code=code,
        phase_when_fired=Phase.CRUISE,
        phase_source_when_fired=PhaseSource.FLIGHTTASK_STEP_CODE,
        facts={}, thresholds={}, suggested_action="notify",
        context=ctx, ts_ms=ts, dedup_key=f"r1#{ts // 1000}",
    )


def _params(default_cd: int = 30000, em_floor: int = 2000) -> CoordinatorParams:
    return CoordinatorParams(
        default_cooldown_ms=default_cd,
        emergency_floor_cooldown_ms=em_floor,
        dedup_window_ms=60000,
        dedup_burst_threshold=10,
    )


class TestCooldown:
    def test_first_fire_passes(self) -> None:
        gate = CooldownGate(_params())
        assert gate.check_and_record(_v(1000)) == "pass"

    def test_within_cooldown_suppressed(self) -> None:
        gate = CooldownGate(_params(default_cd=30000))
        assert gate.check_and_record(_v(1000)) == "pass"
        assert gate.check_and_record(_v(5000)) == "suppressed_cooldown"

    def test_after_cooldown_re_passes(self) -> None:
        gate = CooldownGate(_params(default_cd=30000))
        assert gate.check_and_record(_v(1000)) == "pass"
        assert gate.check_and_record(_v(35000)) == "pass"

    def test_different_codes_independent(self) -> None:
        gate = CooldownGate(_params())
        assert gate.check_and_record(_v(1000, code="A")) == "pass"
        assert gate.check_and_record(_v(1500, code="B")) == "pass"

    def test_different_dock_sn_independent(self) -> None:
        gate = CooldownGate(_params())
        assert gate.check_and_record(_v(1000, dock_sn="D1")) == "pass"
        assert gate.check_and_record(_v(1500, dock_sn="D2")) == "pass"

    def test_emergency_uses_floor(self) -> None:
        gate = CooldownGate(_params(default_cd=30000, em_floor=2000))
        assert gate.check_and_record(_v(1000, level=Severity.EMERGENCY)) == "pass"
        assert gate.check_and_record(_v(2000, level=Severity.EMERGENCY)) == "suppressed_cooldown"
        assert gate.check_and_record(_v(3100, level=Severity.EMERGENCY)) == "pass"
