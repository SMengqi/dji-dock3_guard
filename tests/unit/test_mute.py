"""Phase 5 单元测试: MuteState (设计 §6.5)."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from dock_guard.coordinator.mute import MuteState
from dock_guard.rules.verdict import Verdict
from dock_guard.types import Phase, PhaseSource, Severity


def _v(ts: int, level: Severity, dock_sn: str = "D1") -> Verdict:
    ctx: Mapping[str, Any] = MappingProxyType({"dock_sn": dock_sn})
    return Verdict(
        rule_id="r1", level=level, code="X",
        phase_when_fired=Phase.CRUISE,
        phase_source_when_fired=PhaseSource.FLIGHTTASK_STEP_CODE,
        facts={}, thresholds={}, suggested_action="notify",
        context=ctx, ts_ms=ts, dedup_key="X",
    )


class TestDockMute:
    def test_no_mute_default_pass(self) -> None:
        m = MuteState()
        assert m.check(_v(1000, Severity.WARN), now_ms=1000) == "pass"

    def test_dock_mute_blocks_below_threshold(self) -> None:
        m = MuteState()
        m.set_dock_mute("D1", enabled=True, min_severity_to_send=Severity.EMERGENCY,
                        duration_s=600, now_ms=1000)
        assert m.check(_v(1500, Severity.WARN), now_ms=1500) == "muted_dock"
        assert m.check(_v(1500, Severity.EMERGENCY), now_ms=1500) == "pass"

    def test_dock_mute_other_dock_unaffected(self) -> None:
        m = MuteState()
        m.set_dock_mute("D1", enabled=True, min_severity_to_send=Severity.EMERGENCY,
                        duration_s=600, now_ms=1000)
        assert m.check(_v(1500, Severity.WARN, dock_sn="D2"), now_ms=1500) == "pass"

    def test_dock_mute_expires(self) -> None:
        m = MuteState()
        m.set_dock_mute("D1", enabled=True, min_severity_to_send=Severity.EMERGENCY,
                        duration_s=10, now_ms=1000)
        assert m.check(_v(9000, Severity.WARN), now_ms=9000) == "muted_dock"
        assert m.check(_v(12000, Severity.WARN), now_ms=12000) == "pass"


class TestGlobalMute:
    def test_global_mute_blocks_below_threshold(self) -> None:
        m = MuteState()
        m.set_global_mute(enabled=True, min_severity_to_send=Severity.BLOCK, now_ms=1000)
        assert m.check(_v(1500, Severity.WARN), now_ms=1500) == "muted_global"
        assert m.check(_v(1500, Severity.BLOCK), now_ms=1500) == "pass"

    def test_global_disable_unmutes(self) -> None:
        m = MuteState()
        m.set_global_mute(enabled=True, min_severity_to_send=Severity.BLOCK, now_ms=1000)
        m.set_global_mute(enabled=False, now_ms=2000)
        assert m.check(_v(3000, Severity.WARN), now_ms=3000) == "pass"

    def test_global_mute_takes_priority(self) -> None:
        m = MuteState()
        m.set_global_mute(enabled=True, min_severity_to_send=Severity.EMERGENCY, now_ms=1000)
        m.set_dock_mute("D1", enabled=True, min_severity_to_send=Severity.WARN,
                        duration_s=0, now_ms=1000)
        assert m.check(_v(1500, Severity.WARN), now_ms=1500) == "muted_global"
