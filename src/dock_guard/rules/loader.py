"""rules.yaml 加载与 pydantic schema (设计 §5.7.1)."""

from __future__ import annotations

import pathlib
from collections.abc import Iterator
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dock_guard.aggregator.facts import F
from dock_guard.rules.custom_fns import CustomFnEnum
from dock_guard.types import Phase, Severity

KNOWN_FACT_NAMES: frozenset[str] = frozenset(
    v for k, v in vars(F).items() if not k.startswith("_") and isinstance(v, str)
)

SUPPORTED_OPS: frozenset[str] = frozenset({
    "==", "!=", ">", ">=", "<", "<=", "in", "not_in", "any_in",
})


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FactCondition(_Strict):
    fact: str
    op: Literal["==", "!=", ">", ">=", "<", "<=", "in", "not_in", "any_in"]
    value: Any = None
    fact_ref: str | None = None
    value_ref: str | None = None

    @field_validator("fact")
    @classmethod
    def _validate_fact_name(cls, v: str) -> str:
        if v not in KNOWN_FACT_NAMES:
            raise ValueError(
                f"unknown fact '{v}'; must be in §5.2 namespace (F class)"
            )
        return v

    @field_validator("fact_ref")
    @classmethod
    def _validate_fact_ref(cls, v: str | None) -> str | None:
        if v is not None and v not in KNOWN_FACT_NAMES:
            raise ValueError(f"unknown fact_ref '{v}'")
        return v

    @model_validator(mode="after")
    def _exactly_one_of_value_factref_valueref(self) -> FactCondition:
        provided = sum(
            x is not None for x in (self.value, self.fact_ref, self.value_ref)
        )
        if provided != 1:
            raise ValueError(
                f"FactCondition must have exactly one of value/fact_ref/value_ref (got {provided})"
            )
        return self


class VerdictSpec(_Strict):
    level: Literal["emergency", "block", "return", "warn", "info"]
    code: str = Field(min_length=1)
    suggested_action: str = "notify"

    def severity(self) -> Severity:
        return Severity[self.level.upper()]


class Rule(_Strict):
    id: str = Field(min_length=1)
    desc: str | None = None
    phase: list[Phase] | None = None
    all_: list[FactCondition] | None = Field(default=None, alias="all")
    any_: list[FactCondition] | None = Field(default=None, alias="any")
    custom_fn: CustomFnEnum | None = None
    custom_args: dict[str, Any] | None = None
    cooldown_ms: int | None = Field(default=None, ge=0)
    dwell_enter_ms: int | None = Field(default=None, ge=0)
    dwell_exit_ms: int | None = Field(default=None, ge=0)
    verdict: VerdictSpec

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    @model_validator(mode="after")
    def _exactly_one_of_all_any_custom(self) -> Rule:
        provided = sum(x is not None for x in (self.all_, self.any_, self.custom_fn))
        if provided != 1:
            raise ValueError(
                f"Rule '{self.id}' must have exactly one of all/any/custom_fn (got {provided})"
            )
        return self

    @model_validator(mode="after")
    def _custom_args_only_with_custom_fn(self) -> Rule:
        if self.custom_args is not None and self.custom_fn is None:
            raise ValueError(f"Rule '{self.id}': custom_args requires custom_fn")
        return self


class RuleDefaults(_Strict):
    cooldown_ms: int = Field(default=30000, ge=0)
    dwell_enter_ms: int = Field(default=0, ge=0)
    dwell_exit_ms: int = Field(default=0, ge=0)


class RulesYaml(_Strict):
    version: Literal[2]
    defaults: RuleDefaults = RuleDefaults()
    preflight_block: list[Rule] = []
    inflight_escalate: list[Rule] = []
    airspace_conflict: list[Rule] = []
    maintenance_advisory: list[Rule] = []
    analytics_driven: list[Rule] = []

    def all_rules(self) -> Iterator[Rule]:
        yield from self.preflight_block
        yield from self.inflight_escalate
        yield from self.airspace_conflict
        yield from self.maintenance_advisory
        yield from self.analytics_driven

    @model_validator(mode="after")
    def _unique_rule_ids(self) -> RulesYaml:
        seen: set[str] = set()
        for r in self.all_rules():
            if r.id in seen:
                raise ValueError(f"duplicate rule id: {r.id}")
            seen.add(r.id)
        return self


def load_rules_yaml(path: pathlib.Path) -> RulesYaml:
    if not path.exists():
        raise FileNotFoundError(f"rules.yaml not found: {path}")
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    return RulesYaml.model_validate(data)
