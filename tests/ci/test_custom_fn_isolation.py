"""Stage 3-D B2: custom_fn 异常隔离 + RULE_EVAL_FAILED 自产 (设计 §5.4 / §12.4).

设计 §5.4 强约束: yaml 引用的 custom_fn 在 Python 端抛异常时,
1. 该规则当前 tick 视未触发 (不产业务 Verdict);
2. 其它规则照常评估 (异常隔离);
3. eval_failure_counts[rule.id] +1 (Phase 9 metric 来源);
4. 自产 'RULE_EVAL_FAILED' WARN 级 Verdict 一条 (下游审计 + 钉钉可知).

这一套是 spec 的硬合规, CI 强制门, 任何改 RuleEngine 都不能破.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from dock_guard.rules.custom_fns import CustomFnContext, CustomFnEnum, CustomFnResult
from dock_guard.rules.engine import RuleEngine
from dock_guard.rules.loader import RulesYaml
from dock_guard.types import Severity


def _rules_with_two_custom_fn() -> RulesYaml:
    """一条 custom_fn 规则故意炸 + 一条普通 fact 规则 (warming_up==true).
    用于测异常隔离不影响其它规则."""
    raw = yaml.safe_load("""
        version: 2
        defaults:
          cooldown_ms: 30000
          dwell_enter_ms: 0
          dwell_exit_ms: 0
        preflight_block:
          - id: a.boomer
            desc: 故意炸的 custom_fn (测试用)
            phase: null
            custom_fn: is_battery_drop_normal
            verdict:
              level: warn
              code: BOOMER_FIRES
              suggested_action: investigate
          - id: a.normal
            desc: 永远触发的普通比较规则 (测试用)
            phase: null
            all:
              - { fact: warming_up, op: "==", value: true }
            verdict:
              level: info
              code: NORMAL_FIRES
              suggested_action: notify
        inflight_escalate: []
        maintenance_advisory: []
    """)
    return RulesYaml.model_validate(raw)


class FakeFactsRing:
    pass


class FakeFrame:
    def __init__(self, facts: dict[str, Any], ts_ms: int = 1700000000000) -> None:
        self.facts = facts
        self.recv_ts_ms = ts_ms


class FakeAgg:
    """最小 aggregator: 只暴露 latest_facts() + facts_ring."""

    def __init__(self, facts: dict[str, Any]) -> None:
        self._facts = facts
        self.facts_ring = FakeFactsRing()

    def latest_facts(self) -> FakeFrame:
        return FakeFrame(self._facts)


def _boom_custom_fn(ctx: CustomFnContext) -> CustomFnResult:
    raise RuntimeError("intentional boom for test")


@pytest.fixture
def engine_with_boom() -> RuleEngine:
    agg = FakeAgg({
        "warming_up": True,
        "dock_sn": "TEST_DOCK_01",
        "drone_sn": "TEST_DRONE_01",
    })
    return RuleEngine(
        _rules_with_two_custom_fn(),
        agg,   # type: ignore[arg-type]
        custom_fns={CustomFnEnum.is_battery_drop_normal: _boom_custom_fn},
    )


class TestExceptionDoesNotProduceBusinessVerdict:
    def test_boomer_rule_does_not_fire_business_verdict(
        self, engine_with_boom: RuleEngine
    ) -> None:
        verdicts = engine_with_boom.evaluate()
        business = [v for v in verdicts if v.code == "BOOMER_FIRES"]
        assert not business, (
            "抛异常的 custom_fn 规则不应当产出业务 Verdict (设计 §5.4)"
        )


class TestOtherRulesStillEvaluate:
    def test_normal_rule_still_fires(self, engine_with_boom: RuleEngine) -> None:
        verdicts = engine_with_boom.evaluate()
        normal = [v for v in verdicts if v.code == "NORMAL_FIRES"]
        assert len(normal) == 1, (
            "异常隔离不应当影响其它规则评估 (设计 §5.4); 实际得到: "
            f"{[v.code for v in verdicts]}"
        )


class TestFailureCounter:
    def test_counter_increments_per_failure(self, engine_with_boom: RuleEngine) -> None:
        assert engine_with_boom.eval_failure_counts == {}
        engine_with_boom.evaluate()
        assert engine_with_boom.eval_failure_counts.get("a.boomer") == 1
        engine_with_boom.evaluate()
        assert engine_with_boom.eval_failure_counts.get("a.boomer") == 2


class TestSelfProducedFailureVerdict:
    def test_failure_verdict_emitted(self, engine_with_boom: RuleEngine) -> None:
        verdicts = engine_with_boom.evaluate()
        failed = [v for v in verdicts if v.code == "RULE_EVAL_FAILED"]
        assert len(failed) == 1
        v = failed[0]
        assert v.level == Severity.WARN
        assert v.rule_id == "system.rule_eval_failed"
        assert v.facts["failed_rule_id"] == "a.boomer"
        assert v.facts["failed_custom_fn"] == "is_battery_drop_normal"
        assert v.facts["exception_type"] == "RuntimeError"
        assert "intentional boom" in v.facts["exception_message"]
        assert "a.boomer" in v.desc

    def test_failures_cleared_between_ticks(
        self, engine_with_boom: RuleEngine
    ) -> None:
        """每 tick 起清空: tick1 失败 1 次产 1 条, tick2 失败 1 次产 1 条
        (而不是 tick2 产 2 条 = tick1 + tick2 累加)."""
        v1 = engine_with_boom.evaluate()
        v2 = engine_with_boom.evaluate()
        assert sum(1 for v in v1 if v.code == "RULE_EVAL_FAILED") == 1
        assert sum(1 for v in v2 if v.code == "RULE_EVAL_FAILED") == 1
