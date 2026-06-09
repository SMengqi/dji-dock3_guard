"""CooldownGate — 设计 §6.3."""

from __future__ import annotations

from dock_guard.config import CoordinatorParams
from dock_guard.rules.verdict import Verdict
from dock_guard.types import Severity


class CooldownGate:
    """单 coordinator 实例持有, 进程内状态."""

    __slots__ = ("_default_ms", "_emergency_floor_ms", "_last_fired")

    def __init__(self, params: CoordinatorParams) -> None:
        self._default_ms = params.default_cooldown_ms
        self._emergency_floor_ms = params.emergency_floor_cooldown_ms
        self._last_fired: dict[tuple[str, str], int] = {}

    def check_and_record(self, verdict: Verdict) -> str:
        """返回 'pass' 或 'suppressed_cooldown'."""
        dock_sn = str(verdict.context.get("dock_sn") or "")
        key = (dock_sn, verdict.code)
        cd_ms = self._cooldown_ms_for(verdict)

        last = self._last_fired.get(key)
        if last is not None and (verdict.ts_ms - last) < cd_ms:
            return "suppressed_cooldown"

        self._last_fired[key] = verdict.ts_ms
        return "pass"

    def _cooldown_ms_for(self, verdict: Verdict) -> int:
        if verdict.level == Severity.EMERGENCY:
            return self._emergency_floor_ms
        # 设计 §6.3: 规则可覆盖默认 cooldown_ms
        if verdict.cooldown_ms_override is not None:
            return verdict.cooldown_ms_override
        return self._default_ms

    def clear(self) -> None:
        self._last_fired.clear()
