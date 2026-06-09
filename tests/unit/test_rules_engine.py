"""Phase 4 单元测试: RuleEngine 评估逻辑 (设计 §5)."""

from __future__ import annotations

import textwrap
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml as pyyaml

from dock_guard.aggregator.facts import freeze_facts
from dock_guard.aggregator.facts_ring import FactsRing
from dock_guard.rules.custom_fns import CustomFnContext, CustomFnEnum, CustomFnResult
from dock_guard.rules.engine import RuleEngine, _apply_op
from dock_guard.rules.loader import RulesYaml
from dock_guard.types import Severity


def _make_agg(facts: dict[str, Any], recv_ts_ms: int = 1000) -> MagicMock:
    agg = MagicMock()
    ring = FactsRing(max_window_ms=300000)
    ring.append(freeze_facts(recv_ts_ms, facts))
    agg.facts_ring = ring
    agg.latest_facts.return_value = ring.latest()
    return agg


def _rules_from_yaml(yaml_text: str) -> RulesYaml:
    return RulesYaml.model_validate(pyyaml.safe_load(textwrap.dedent(yaml_text)))


class TestApplyOp:
    def test_eq(self) -> None:
        assert _apply_op(5, "==", 5) is True
        assert _apply_op(5, "==", 6) is False

    def test_ne(self) -> None:
        assert _apply_op(5, "!=", 6) is True
        assert _apply_op(None, "!=", 5) is False

    def test_gt(self) -> None:
        assert _apply_op(10, ">", 5) is True
        assert _apply_op(5, ">", 10) is False
        assert _apply_op(None, ">", 5) is False

    def test_in(self) -> None:
        assert _apply_op(2, "in", [1, 2, 3]) is True
        assert _apply_op(99, "in", [1, 2, 3]) is False

    def test_any_in(self) -> None:
        assert _apply_op([1, 2], "any_in", [2, 3]) is True
        assert _apply_op([1, 2], "any_in", [99]) is False

    def test_unknown_op(self) -> None:
        with pytest.raises(ValueError):
            _apply_op(1, "?", 2)


class TestRuleEngineBasic:
    def test_all_matches(self) -> None:
        rules = _rules_from_yaml("""
            version: 2
            preflight_block:
              - id: r1
                phase: [PREFLIGHT]
                all:
                  - { fact: tilt_angle_valid, op: "==", value: 1 }
                  - { fact: tilt_angle_value, op: ">", value: 3.0 }
                verdict: { level: block, code: TILT, suggested_action: reject_takeoff }
        """)
        agg = _make_agg({
            "phase": "PREFLIGHT", "phase_source": "flighttask_step_code",
            "tilt_angle_valid": 1, "tilt_angle_value": 5.0,
        })
        eng = RuleEngine(rules, agg)
        verdicts = eng.evaluate()
        assert len(verdicts) == 1
        assert verdicts[0].code == "TILT"
        assert verdicts[0].level == Severity.BLOCK
        assert verdicts[0].suggested_action == "reject_takeoff"

    def test_all_partial_no_fire(self) -> None:
        rules = _rules_from_yaml("""
            version: 2
            preflight_block:
              - id: r1
                phase: [PREFLIGHT]
                all:
                  - { fact: tilt_angle_valid, op: "==", value: 1 }
                  - { fact: tilt_angle_value, op: ">", value: 3.0 }
                verdict: { level: block, code: TILT }
        """)
        agg = _make_agg({
            "phase": "PREFLIGHT", "phase_source": "flighttask_step_code",
            "tilt_angle_valid": 1, "tilt_angle_value": 0.5,
        })
        eng = RuleEngine(rules, agg)
        assert eng.evaluate() == []

    def test_phase_filter(self) -> None:
        rules = _rules_from_yaml("""
            version: 2
            preflight_block:
              - id: r1
                phase: [PREFLIGHT]
                all: [{ fact: warming_up, op: "==", value: true }]
                verdict: { level: block, code: X }
        """)
        agg = _make_agg({
            "phase": "CRUISE", "phase_source": "flighttask_step_code",
            "warming_up": True,
        })
        eng = RuleEngine(rules, agg)
        assert eng.evaluate() == []

    def test_phase_omitted_matches_all(self) -> None:
        rules = _rules_from_yaml("""
            version: 2
            maintenance_advisory:
              - id: r1
                all: [{ fact: warming_up, op: "==", value: true }]
                verdict: { level: info, code: WARMUP }
        """)
        agg = _make_agg({
            "phase": "OFFLINE", "phase_source": "fallback_idle",
            "warming_up": True,
        })
        eng = RuleEngine(rules, agg)
        assert len(eng.evaluate()) == 1


class TestFactRef:
    def test_battery_low_fires_when_below(self) -> None:
        rules = _rules_from_yaml("""
            version: 2
            inflight_escalate:
              - id: r1
                phase: [CRUISE]
                all:
                  - { fact: battery_capacity_percent, op: "<=", fact_ref: battery_return_home_power }
                verdict: { level: return, code: BAT_LOW, suggested_action: return_home }
        """)
        agg = _make_agg({
            "phase": "CRUISE", "phase_source": "flighttask_step_code",
            "battery_capacity_percent": 30, "battery_return_home_power": 35,
        })
        eng = RuleEngine(rules, agg)
        assert len(eng.evaluate()) == 1

    def test_battery_low_no_fire_when_above(self) -> None:
        rules = _rules_from_yaml("""
            version: 2
            inflight_escalate:
              - id: r1
                phase: [CRUISE]
                all:
                  - { fact: battery_capacity_percent, op: "<=", fact_ref: battery_return_home_power }
                verdict: { level: return, code: BAT_LOW }
        """)
        agg = _make_agg({
            "phase": "CRUISE", "phase_source": "flighttask_step_code",
            "battery_capacity_percent": 80, "battery_return_home_power": 35,
        })
        eng = RuleEngine(rules, agg)
        assert eng.evaluate() == []


class TestDwell:
    def test_dwell_holds_initial_match(self) -> None:
        rules = _rules_from_yaml("""
            version: 2
            inflight_escalate:
              - id: r1
                phase: [CRUISE]
                all: [{ fact: wind_gust_max_30s, op: ">", value: 14.0 }]
                dwell_enter_ms: 3000
                verdict: { level: return, code: GUST }
        """)
        agg = _make_agg({
            "phase": "CRUISE", "phase_source": "flighttask_step_code",
            "wind_gust_max_30s": 20.0,
        }, recv_ts_ms=1000)
        eng = RuleEngine(rules, agg)
        assert eng.evaluate() == []

        agg2 = _make_agg({
            "phase": "CRUISE", "phase_source": "flighttask_step_code",
            "wind_gust_max_30s": 20.0,
        }, recv_ts_ms=2000)
        eng.aggregator = agg2  # type: ignore[assignment]
        assert eng.evaluate() == []

        agg3 = _make_agg({
            "phase": "CRUISE", "phase_source": "flighttask_step_code",
            "wind_gust_max_30s": 20.0,
        }, recv_ts_ms=5000)
        eng.aggregator = agg3  # type: ignore[assignment]
        verdicts = eng.evaluate()
        assert len(verdicts) == 1

    def test_dwell_resets_on_no_match(self) -> None:
        rules = _rules_from_yaml("""
            version: 2
            inflight_escalate:
              - id: r1
                phase: [CRUISE]
                all: [{ fact: wind_gust_max_30s, op: ">", value: 14.0 }]
                dwell_enter_ms: 3000
                verdict: { level: return, code: GUST }
        """)
        ctx = {"phase": "CRUISE", "phase_source": "flighttask_step_code"}

        agg = _make_agg({**ctx, "wind_gust_max_30s": 20.0}, recv_ts_ms=1000)
        eng = RuleEngine(rules, agg)
        eng.evaluate()

        agg2 = _make_agg({**ctx, "wind_gust_max_30s": 5.0}, recv_ts_ms=2000)
        eng.aggregator = agg2  # type: ignore[assignment]
        eng.evaluate()

        agg3 = _make_agg({**ctx, "wind_gust_max_30s": 20.0}, recv_ts_ms=5000)
        eng.aggregator = agg3  # type: ignore[assignment]
        assert eng.evaluate() == [], "dwell 应被重置"


class TestCustomFn:
    def test_stub_custom_fn_never_fires(self) -> None:
        rules = _rules_from_yaml("""
            version: 2
            analytics_driven:
              - id: r1
                phase: [CRUISE]
                custom_fn: is_battery_drop_normal
                custom_args: { window_ms: 60000 }
                verdict: { level: warn, code: BDR }
        """)
        agg = _make_agg({"phase": "CRUISE", "phase_source": "flighttask_step_code"})
        eng = RuleEngine(rules, agg)
        assert eng.evaluate() == []

    def test_overridden_custom_fn_fires(self) -> None:
        rules = _rules_from_yaml("""
            version: 2
            analytics_driven:
              - id: r1
                phase: [CRUISE]
                custom_fn: is_battery_drop_normal
                verdict: { level: warn, code: BDR, suggested_action: investigate }
        """)
        agg = _make_agg({"phase": "CRUISE", "phase_source": "flighttask_step_code"})

        def custom_fires(ctx: CustomFnContext) -> CustomFnResult:
            return CustomFnResult(matched=True, facts_for_audit={"observed_dcap": 5.5})

        eng = RuleEngine(rules, agg,
                         custom_fns={CustomFnEnum.is_battery_drop_normal: custom_fires})
        verdicts = eng.evaluate()
        assert len(verdicts) == 1
        assert verdicts[0].code == "BDR"
        assert verdicts[0].facts["observed_dcap"] == 5.5

    def test_custom_fn_exception_isolated(self) -> None:
        rules = _rules_from_yaml("""
            version: 2
            analytics_driven:
              - id: r1
                phase: [CRUISE]
                custom_fn: is_battery_drop_normal
                verdict: { level: warn, code: BDR }
              - id: r2
                phase: [CRUISE]
                all: [{ fact: warming_up, op: "==", value: true }]
                verdict: { level: info, code: OK }
            maintenance_advisory: []
        """)
        agg = _make_agg({"phase": "CRUISE", "phase_source": "flighttask_step_code",
                         "warming_up": True})

        def boom(ctx: CustomFnContext) -> CustomFnResult:
            raise RuntimeError("boom")

        eng = RuleEngine(rules, agg,
                         custom_fns={CustomFnEnum.is_battery_drop_normal: boom})
        verdicts = eng.evaluate()
        assert {v.code for v in verdicts} == {"OK"}
