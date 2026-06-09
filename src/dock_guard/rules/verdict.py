"""Verdict — 规则评估输出 (设计 §5.6)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from dock_guard.types import Phase, PhaseSource, Severity


@dataclass(frozen=True, slots=True)
class Verdict:
    """规则触发结果. 设计 §5.6 schema."""

    rule_id: str
    level: Severity
    code: str
    phase_when_fired: Phase
    phase_source_when_fired: PhaseSource
    facts: Mapping[str, Any]
    thresholds: Mapping[str, str]
    suggested_action: str
    context: Mapping[str, Any]
    ts_ms: int
    dedup_key: str
    cooldown_ms_override: int | None = None    # 规则级 cooldown_ms 覆盖, 由 engine 填

    @property
    def severity_name(self) -> str:
        return self.level.name
