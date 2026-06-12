"""RuleEngine — 评估 facts 产出 Verdict (设计 §5)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from dock_guard.aggregator import DockAggregator
from dock_guard.aggregator.facts import FrozenFacts
from dock_guard.rules.custom_fns import (
    CUSTOM_FN_WHITELIST,
    CustomFn,
    CustomFnContext,
    CustomFnEnum,
)
from dock_guard.rules.loader import FactCondition, Rule, RulesYaml
from dock_guard.rules.verdict import Verdict
from dock_guard.types import Phase, PhaseSource, Severity


@dataclass
class _DwellState:
    matching_since_ms: int


class RuleEngine:
    """规则引擎. 每 dock 一个实例, 持有该 dock 的 dwell 状态."""

    def __init__(
        self,
        rules: RulesYaml,
        aggregator: DockAggregator,
        *,
        custom_fns: Mapping[CustomFnEnum, CustomFn] = CUSTOM_FN_WHITELIST,
        value_refs: Mapping[str, frozenset[Any]] | None = None,
    ) -> None:
        self.rules = rules
        self.aggregator = aggregator
        self.custom_fns = dict(custom_fns)
        self.value_refs: Mapping[str, frozenset[Any]] = value_refs or {}
        self._dwell_state: dict[str, _DwellState] = {}
        # Stage 3-D B2: custom_fn 异常隔离审计 (§5.4).
        # eval_failure_counts: per-rule_id 计数, Phase 9 metric 来源.
        # _failures_this_tick: 当 tick 自产的 RULE_EVAL_FAILED 列表;
        # evaluate() 末尾 extend 到返回 verdicts 里, 下一 tick 起始清空.
        self.eval_failure_counts: dict[str, int] = {}
        self._failures_this_tick: list[Verdict] = []

    def evaluate(self) -> list[Verdict]:
        """评估当前 latest facts, 返回触发的 Verdict 列表 (含 RULE_EVAL_FAILED 自产)."""
        frame = self.aggregator.latest_facts()
        if frame is None:
            return []

        # Stage 3-D B2: 每 tick 起清空自产 failure 队列 (上 tick 已经返出去)
        self._failures_this_tick = []

        facts = frame.facts
        current_phase = self._phase_from(facts)
        current_phase_source = self._phase_source_from(facts)

        verdicts: list[Verdict] = []
        for rule in self.rules.all_rules():
            if rule.phase is not None and current_phase not in rule.phase:
                self._dwell_state.pop(rule.id, None)
                continue

            matched, audit_facts, audit_thresholds = self._eval_rule_body(rule, frame)

            if not matched:
                self._dwell_state.pop(rule.id, None)
                continue

            if not self._dwell_passes(rule, frame.recv_ts_ms):
                continue

            verdicts.append(self._build_verdict(
                rule, frame, current_phase, current_phase_source,
                audit_facts, audit_thresholds,
            ))

        # Stage 3-D B2: custom_fn 异常自产的 RULE_EVAL_FAILED 也透到下游
        # (走 AlertCoordinator 三闸 + 钉钉 / SSE / alerts.jsonl 同流程).
        verdicts.extend(self._failures_this_tick)
        return verdicts

    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _phase_from(facts: Mapping[str, Any]) -> Phase | None:
        raw = facts.get("phase")
        if raw is None:
            return None
        try:
            return Phase(raw)
        except ValueError:
            return None

    @staticmethod
    def _phase_source_from(facts: Mapping[str, Any]) -> PhaseSource | None:
        raw = facts.get("phase_source")
        if raw is None:
            return None
        try:
            return PhaseSource(raw)
        except ValueError:
            return None

    def _eval_rule_body(
        self, rule: Rule, frame: FrozenFacts
    ) -> tuple[bool, dict[str, Any], dict[str, str]]:
        if rule.all_ is not None:
            return self._eval_combinator(rule.all_, frame.facts, mode="all")
        if rule.any_ is not None:
            return self._eval_combinator(rule.any_, frame.facts, mode="any")
        if rule.custom_fn is not None:
            return self._eval_custom_fn(rule, frame)
        return False, {}, {}

    def _eval_combinator(
        self,
        conds: list[FactCondition],
        facts: Mapping[str, Any],
        *,
        mode: str,
    ) -> tuple[bool, dict[str, Any], dict[str, str]]:
        audit_facts: dict[str, Any] = {}
        audit_thresholds: dict[str, str] = {}
        results: list[bool] = []
        for cond in conds:
            actual = facts.get(cond.fact)
            target = self._resolve_target(cond, facts)
            ok = _apply_op(actual, cond.op, target)
            results.append(ok)
            audit_facts[cond.fact] = actual
            audit_thresholds[cond.fact] = _threshold_str(cond)
        matched = all(results) if mode == "all" else any(results)
        return matched, audit_facts, audit_thresholds

    def _resolve_target(self, cond: FactCondition, facts: Mapping[str, Any]) -> Any:
        if cond.value is not None:
            return cond.value
        if cond.fact_ref is not None:
            return facts.get(cond.fact_ref)
        if cond.value_ref is not None:
            return self.value_refs.get(cond.value_ref, frozenset())
        return None

    def _eval_custom_fn(
        self, rule: Rule, frame: FrozenFacts
    ) -> tuple[bool, dict[str, Any], dict[str, str]]:
        assert rule.custom_fn is not None
        fn = self.custom_fns[rule.custom_fn]
        ctx = CustomFnContext(
            rule_id=rule.id,
            facts=frame.facts,
            facts_ring=self.aggregator.facts_ring,
            custom_args=rule.custom_args or {},
            recv_ts_ms=frame.recv_ts_ms,
        )
        try:
            result = fn(ctx)
        except Exception as e:
            # 设计 §5.4: custom_fn 抛异常 → 视未触发 + 计数 + 自产
            # RULE_EVAL_FAILED WARN. 其它规则不受影响 (本函数返 False 即可).
            self.eval_failure_counts[rule.id] = (
                self.eval_failure_counts.get(rule.id, 0) + 1
            )
            self._failures_this_tick.append(
                self._build_eval_failed_verdict(rule, frame, e)
            )
            return False, {}, {}
        audit_facts = dict(result.facts_for_audit)
        return result.matched, audit_facts, {}

    def _dwell_passes(self, rule: Rule, recv_ts_ms: int) -> bool:
        dwell = rule.dwell_enter_ms or self.rules.defaults.dwell_enter_ms
        if dwell == 0:
            self._dwell_state.pop(rule.id, None)
            return True
        state = self._dwell_state.get(rule.id)
        if state is None:
            self._dwell_state[rule.id] = _DwellState(matching_since_ms=recv_ts_ms)
            return False
        return (recv_ts_ms - state.matching_since_ms) >= dwell

    def _build_verdict(
        self,
        rule: Rule,
        frame: FrozenFacts,
        current_phase: Phase | None,
        current_phase_source: PhaseSource | None,
        audit_facts: dict[str, Any],
        audit_thresholds: dict[str, str],
    ) -> Verdict:
        return Verdict(
            rule_id=rule.id,
            level=rule.verdict.severity(),
            code=rule.verdict.code,
            phase_when_fired=current_phase or Phase.OFFLINE,
            phase_source_when_fired=current_phase_source or PhaseSource.FALLBACK_IDLE,
            facts=audit_facts,
            thresholds=audit_thresholds,
            suggested_action=rule.verdict.suggested_action,
            context={
                "dock_sn": frame.facts.get("dock_sn"),
                "drone_sn": frame.facts.get("drone_sn"),
            },
            ts_ms=frame.recv_ts_ms,
            dedup_key=f"{rule.id}#{frame.recv_ts_ms // 1000}",
            cooldown_ms_override=rule.cooldown_ms,
            desc=rule.desc,
        )

    def _build_eval_failed_verdict(
        self,
        rule: Rule,
        frame: FrozenFacts,
        exc: Exception,
    ) -> Verdict:
        """Stage 3-D B2: custom_fn 异常时自产的 WARN 级 Verdict.

        rule_id 用 'system.rule_eval_failed' 区分本系统产物 vs 业务规则
        (方便 alerts.jsonl 检索 + 钉钉 routing 分流). dedup_key 含失败的
        rule.id, 让同一 rule 的反复失败被 AlertCoordinator dedup gate 合并.
        """
        return Verdict(
            rule_id="system.rule_eval_failed",
            level=Severity.WARN,
            code="RULE_EVAL_FAILED",
            phase_when_fired=self._phase_from(frame.facts) or Phase.OFFLINE,
            phase_source_when_fired=(
                self._phase_source_from(frame.facts) or PhaseSource.FALLBACK_IDLE
            ),
            facts={
                "failed_rule_id": rule.id,
                "failed_custom_fn": rule.custom_fn.value if rule.custom_fn else None,
                "exception_type": type(exc).__name__,
                "exception_message": str(exc)[:200],
            },
            thresholds={},
            suggested_action="investigate",
            context={
                "dock_sn": frame.facts.get("dock_sn"),
                "drone_sn": frame.facts.get("drone_sn"),
            },
            ts_ms=frame.recv_ts_ms,
            dedup_key=f"system.rule_eval_failed#{rule.id}#{frame.recv_ts_ms // 1000}",
            cooldown_ms_override=None,
            desc=f"规则评估失败 (custom_fn 异常隔离): {rule.id}",
        )


# ─── op 实现 ────────────────────────────────────────────────────────


def _apply_op(actual: Any, op: str, target: Any) -> bool:
    if op == "==":
        return actual == target
    if op == "!=":
        return actual is not None and actual != target
    if actual is None:
        return False
    if op == ">":
        return _safe_cmp(actual, target, lambda a, b: a > b)
    if op == ">=":
        return _safe_cmp(actual, target, lambda a, b: a >= b)
    if op == "<":
        return _safe_cmp(actual, target, lambda a, b: a < b)
    if op == "<=":
        return _safe_cmp(actual, target, lambda a, b: a <= b)
    if op == "in":
        if target is None:
            return False
        try:
            return actual in target
        except TypeError:
            return False
    if op == "not_in":
        if target is None:
            return True
        try:
            return actual not in target
        except TypeError:
            return False
    if op == "any_in":
        if target is None:
            return False
        try:
            return bool(set(actual) & set(target))
        except TypeError:
            return False
    raise ValueError(f"unknown op '{op}'")


def _safe_cmp(a: Any, b: Any, fn: Any) -> bool:
    try:
        return bool(fn(a, b))
    except TypeError:
        return False


def _threshold_str(cond: FactCondition) -> str:
    if cond.value is not None:
        return f"{cond.op}{cond.value!r}"
    if cond.fact_ref is not None:
        return f"{cond.op}@{cond.fact_ref}"
    if cond.value_ref is not None:
        return f"{cond.op}@{cond.value_ref}"
    return cond.op
