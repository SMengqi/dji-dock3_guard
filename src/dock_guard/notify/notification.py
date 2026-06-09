"""统一 Notification 模型 (设计 §7.1)."""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from dock_guard.coordinator.alert_record import AlertRecord
from dock_guard.types import Severity


@dataclass(frozen=True, slots=True)
class Notification:
    """通道投递的归一对象 (设计 §7.1)."""

    id: str
    ts_ms: int
    source: str
    severity: Severity
    code: str
    title: str
    summary: str
    context: Mapping[str, Any]
    suggested_action: str
    dedup_key: str
    links: Mapping[str, str] = field(default_factory=dict)
    verdict_payload: Mapping[str, Any] | None = None

    @classmethod
    def from_alert_record(cls, record: AlertRecord) -> Notification:
        v = record.verdict
        title = f"[{v.level.name}] {v.code}"
        fact_kv = ", ".join(
            f"{k}={vv!r}" for k, vv in list(v.facts.items())[:3]
        )
        summary = (
            f"{record.dock_sn} {v.phase_when_fired.value} "
            f"{v.code}. facts={{ {fact_kv} }}. "
            f"建议: {v.suggested_action} (本系统不下发指令)"
        )
        return cls(
            id=f"notif_{secrets.token_hex(8)}",
            ts_ms=record.ts_ms,
            source="rule_verdict",
            severity=v.level,
            code=v.code,
            title=title,
            summary=summary,
            context={
                "dock_sn": record.dock_sn,
                "drone_sn": record.drone_sn,
                "phase": v.phase_when_fired.value,
                "phase_source": v.phase_source_when_fired.value,
                **{k: vv for k, vv in v.context.items()
                   if k not in ("dock_sn", "drone_sn")},
            },
            suggested_action=v.suggested_action,
            dedup_key=v.dedup_key,
            links={"alert_ref": record.verdict_ref},
            verdict_payload={
                "level": v.level.name,
                "code": v.code,
                "phase_when_fired": v.phase_when_fired.value,
                "facts": dict(v.facts),
                "thresholds": dict(v.thresholds),
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts_ms": self.ts_ms,
            "source": self.source,
            "severity": self.severity.name,
            "code": self.code,
            "title": self.title,
            "summary": self.summary,
            "context": dict(self.context),
            "suggested_action": self.suggested_action,
            "dedup_key": self.dedup_key,
            "links": dict(self.links),
            "verdict": dict(self.verdict_payload) if self.verdict_payload else None,
        }
