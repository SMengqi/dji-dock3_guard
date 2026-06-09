"""DedupGate — 设计 §6.4."""

from __future__ import annotations

from collections import deque
from enum import StrEnum

from dock_guard.config import CoordinatorParams
from dock_guard.rules.verdict import Verdict
from dock_guard.types import Severity


class DedupStatus(StrEnum):
    PASS = "pass"
    COALESCED = "coalesced"


class DedupGate:
    __slots__ = ("_burst_threshold", "_history", "_window_ms")

    def __init__(self, params: CoordinatorParams) -> None:
        self._window_ms = params.dedup_window_ms
        self._burst_threshold = params.dedup_burst_threshold
        self._history: dict[str, deque[int]] = {}

    def check_and_record(self, verdict: Verdict) -> DedupStatus:
        if verdict.level == Severity.EMERGENCY:
            return DedupStatus.PASS  # 设计 §6.4: emergency 不参与合并

        key = verdict.dedup_key
        hist = self._history.setdefault(key, deque())

        cutoff = verdict.ts_ms - self._window_ms
        while hist and hist[0] < cutoff:
            hist.popleft()

        hist.append(verdict.ts_ms)
        if len(hist) > self._burst_threshold:
            return DedupStatus.COALESCED
        return DedupStatus.PASS

    def clear(self) -> None:
        self._history.clear()
