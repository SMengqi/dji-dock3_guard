"""时间窗口派生量 (设计 §4.5)."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable


class TimeBoundedDeque:
    """按时间维护滑窗的 deque (单 dock+drone 实例使用,无锁)."""

    __slots__ = ("_buf", "_window_ms")

    def __init__(self, window_ms: int) -> None:
        if window_ms <= 0:
            raise ValueError(f"window_ms must be >0, got {window_ms}")
        self._window_ms = window_ms
        self._buf: deque[tuple[int, float]] = deque()

    @property
    def window_ms(self) -> int:
        return self._window_ms

    def __len__(self) -> int:
        return len(self._buf)

    def push(self, recv_ts_ms: int, value: float) -> None:
        """追加并自动驱逐窗口外旧值. 乱序点直接丢 (§4.6)."""
        if self._buf and recv_ts_ms < self._buf[-1][0]:
            return
        self._buf.append((recv_ts_ms, value))
        cutoff = recv_ts_ms - self._window_ms
        while self._buf and self._buf[0][0] < cutoff:
            self._buf.popleft()

    def values(self) -> Iterable[float]:
        return (v for _, v in self._buf)

    def max(self) -> float | None:
        if not self._buf:
            return None
        return max(v for _, v in self._buf)

    def latest(self) -> tuple[int, float] | None:
        return self._buf[-1] if self._buf else None

    def clear(self) -> None:
        self._buf.clear()
