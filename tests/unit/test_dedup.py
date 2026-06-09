"""Phase 5 单元测试: DedupGate (设计 §6.4)."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from dock_guard.config import CoordinatorParams
from dock_guard.coordinator.dedup import DedupGate, DedupStatus
from dock_guard.rules.verdict import Verdict
from dock_guard.types import Phase, PhaseSource, Severity


def _v(ts: int, code: str = "X", level: Severity = Severity.WARN,
       dedup_key: str | None = None) -> Verdict:
    ctx: Mapping[str, Any] = MappingProxyType({"dock_sn": "D1"})
    return Verdict(
        rule_id="r1", level=level, code=code,
        phase_when_fired=Phase.CRUISE,
        phase_source_when_fired=PhaseSource.FLIGHTTASK_STEP_CODE,
        facts={}, thresholds={}, suggested_action="notify",
        context=ctx, ts_ms=ts,
        dedup_key=dedup_key or f"r1#{code}",
    )


def _params(window: int = 60000, burst: int = 10) -> CoordinatorParams:
    return CoordinatorParams(
        default_cooldown_ms=30000,
        emergency_floor_cooldown_ms=2000,
        dedup_window_ms=window,
        dedup_burst_threshold=burst,
    )


class TestDedup:
    def test_under_threshold_pass(self) -> None:
        gate = DedupGate(_params(burst=10))
        for i in range(10):
            assert gate.check_and_record(_v(i * 100)) == DedupStatus.PASS

    def test_burst_coalesces(self) -> None:
        gate = DedupGate(_params(burst=10))
        for i in range(10):
            gate.check_and_record(_v(i * 100))
        assert gate.check_and_record(_v(2000)) == DedupStatus.COALESCED

    def test_sliding_window_drops_old(self) -> None:
        gate = DedupGate(_params(window=60000, burst=10))
        for i in range(10):
            gate.check_and_record(_v(i * 100))
        assert gate.check_and_record(_v(70000)) == DedupStatus.PASS

    def test_emergency_skips_dedup(self) -> None:
        gate = DedupGate(_params(burst=5))
        for i in range(10):
            r = gate.check_and_record(_v(i * 100, level=Severity.EMERGENCY))
            assert r == DedupStatus.PASS

    def test_different_dedup_keys_independent(self) -> None:
        gate = DedupGate(_params(burst=10))
        for i in range(10):
            gate.check_and_record(_v(i * 100, dedup_key="K1"))
        assert gate.check_and_record(_v(2000, dedup_key="K2")) == DedupStatus.PASS
