"""AlertRecord — alerts.jsonl 单行 schema (设计 §6.7)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from dock_guard.rules.verdict import Verdict


class Decision(StrEnum):
    DISPATCHED = "DISPATCHED"
    SUPPRESSED = "SUPPRESSED"


@dataclass(frozen=True, slots=True)
class AlertRecord:
    ts_ms: int
    verdict: Verdict
    decision: Decision
    gates: Mapping[str, str]
    channels: Mapping[str, Any] = field(default_factory=dict)

    @property
    def dock_sn(self) -> str:
        return str(self.verdict.context.get("dock_sn") or "")

    @property
    def drone_sn(self) -> str | None:
        v = self.verdict.context.get("drone_sn")
        return str(v) if v else None

    @property
    def verdict_ref(self) -> str:
        return f"{self.verdict.rule_id}#{self.verdict.ts_ms}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts_ms": self.ts_ms,
            "dock_sn": self.dock_sn,
            "drone_sn": self.drone_sn,
            "verdict_ref": self.verdict_ref,
            "verdict": {
                "level": self.verdict.level.name,
                "code": self.verdict.code,
                "phase_when_fired": self.verdict.phase_when_fired.value,
                "phase_source": self.verdict.phase_source_when_fired.value,
                "facts": dict(self.verdict.facts),
                "thresholds": dict(self.verdict.thresholds),
            },
            "suggested_action": self.verdict.suggested_action,
            "decision": self.decision.value,
            "gates": dict(self.gates),
            "channels": dict(self.channels),
        }
