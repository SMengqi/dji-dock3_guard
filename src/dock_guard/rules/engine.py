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
from dock_guard.types import Phase, PhaseSource


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

    def evaluate(self) -> list[Verdict]:
        """评估当前 latest facts, 返回触发的 Verdict 列表."""
        frame = self.aggregator.latest_facts()
        if frame is None:
            return []

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
        except Exception:
            # 设计 §5.4: custom_fn 抛异常 → 视未触发 + Phase 9 metric/告警
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
