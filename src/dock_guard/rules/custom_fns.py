"""custom_fn 封闭白名单 (设计 §5.4 / §13.4.4 / §13.5.7)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from dock_guard.aggregator.facts_ring import FactsRing


class CustomFnEnum(StrEnum):
    is_battery_drop_normal = "is_battery_drop_normal"
    estimate_rth_time_seconds_verdict = "estimate_rth_time_seconds_verdict"
    estimate_endurance_seconds_verdict = "estimate_endurance_seconds_verdict"


@dataclass(frozen=True, slots=True)
class CustomFnContext:
    rule_id: str
    facts: Mapping[str, Any]
    facts_ring: FactsRing
    custom_args: Mapping[str, Any]
    recv_ts_ms: int


@dataclass(frozen=True, slots=True)
class CustomFnResult:
    matched: bool
    facts_for_audit: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


CustomFn = Callable[[CustomFnContext], CustomFnResult]


# ─── Phase 4 stubs (Phase 11 接 §13 真实实现) ─────────────────────────


def _stub_is_battery_drop_normal(ctx: CustomFnContext) -> CustomFnResult:
    return CustomFnResult(matched=False)


def _stub_estimate_rth_time_seconds_verdict(ctx: CustomFnContext) -> CustomFnResult:
    return CustomFnResult(matched=False)


def _stub_estimate_endurance_seconds_verdict(ctx: CustomFnContext) -> CustomFnResult:
    return CustomFnResult(matched=False)


CUSTOM_FN_WHITELIST: Mapping[CustomFnEnum, CustomFn] = {
    CustomFnEnum.is_battery_drop_normal: _stub_is_battery_drop_normal,
    CustomFnEnum.estimate_rth_time_seconds_verdict: _stub_estimate_rth_time_seconds_verdict,
    CustomFnEnum.estimate_endurance_seconds_verdict: _stub_estimate_endurance_seconds_verdict,
}


def lookup_custom_fn(name: str) -> CustomFn:
    try:
        key = CustomFnEnum(name)
    except ValueError as e:
        valid = sorted(k.value for k in CustomFnEnum)
        raise ValueError(f"unknown custom_fn '{name}'; must be one of {valid}") from e
    return CUSTOM_FN_WHITELIST[key]
