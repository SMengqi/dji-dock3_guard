"""MuteState — 设计 §6.5.

per-dock + global 静默. 仅影响通道投递, 不影响 verdict 评估和 alerts.jsonl 落盘.
"""

from __future__ import annotations

from dataclasses import dataclass

from dock_guard.rules.verdict import Verdict
from dock_guard.types import Severity


@dataclass(frozen=True, slots=True)
class MuteEntry:
    enabled: bool
    min_severity_to_send: Severity
    reason: str
    expires_at_ms: int       # 0 = 永久
    set_at_ms: int


class MuteState:
    __slots__ = ("_dock_mutes", "_global_mute")

    def __init__(self) -> None:
        self._dock_mutes: dict[str, MuteEntry] = {}
        self._global_mute: MuteEntry | None = None

    def set_dock_mute(
        self,
        dock_sn: str,
        *,
        enabled: bool,
        min_severity_to_send: Severity = Severity.EMERGENCY,
        reason: str = "",
        duration_s: int = 0,
        now_ms: int,
    ) -> MuteEntry:
        expires = 0 if duration_s == 0 else now_ms + duration_s * 1000
        entry = MuteEntry(
            enabled=enabled,
            min_severity_to_send=min_severity_to_send,
            reason=reason,
            expires_at_ms=expires,
            set_at_ms=now_ms,
        )
        self._dock_mutes[dock_sn] = entry
        return entry

    def set_global_mute(
        self,
        *,
        enabled: bool,
        min_severity_to_send: Severity = Severity.BLOCK,
        reason: str = "",
        now_ms: int,
    ) -> MuteEntry:
        entry = MuteEntry(
            enabled=enabled,
            min_severity_to_send=min_severity_to_send,
            reason=reason,
            expires_at_ms=0,
            set_at_ms=now_ms,
        )
        self._global_mute = entry
        return entry

    def get_dock_mute(self, dock_sn: str) -> MuteEntry | None:
        return self._dock_mutes.get(dock_sn)

    def get_global_mute(self) -> MuteEntry | None:
        return self._global_mute

    def check(self, verdict: Verdict, *, now_ms: int) -> str:
        """返回 'pass' / 'muted_global' / 'muted_dock'."""
        gm = self._global_mute
        if gm is not None and gm.enabled and verdict.level < gm.min_severity_to_send:
            return "muted_global"

        dock_sn = str(verdict.context.get("dock_sn") or "")
        if dock_sn:
            dm = self._dock_mutes.get(dock_sn)
            if dm is not None and dm.enabled:
                if dm.expires_at_ms != 0 and now_ms >= dm.expires_at_ms:
                    self._dock_mutes.pop(dock_sn, None)
                elif verdict.level < dm.min_severity_to_send:
                    return "muted_dock"

        return "pass"

    def clear(self) -> None:
        self._dock_mutes.clear()
        self._global_mute = None
