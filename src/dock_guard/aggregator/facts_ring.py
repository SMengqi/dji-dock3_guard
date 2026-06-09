"""FactsRing — 单写多读环形 buffer (设计 §5.2.1)."""

from __future__ import annotations

import bisect
from collections import deque
from collections.abc import Sequence

from dock_guard.aggregator.facts import FrozenFacts


class FactsRing:
    """单写多读. append O(1), slice O(log n) 二分定位."""

    __slots__ = ("_buf", "_max_window_ms")

    def __init__(self, max_window_ms: int, *, expected_eval_hz: int = 10) -> None:
        if max_window_ms <= 0:
            raise ValueError(f"max_window_ms must be >0, got {max_window_ms}")
        if expected_eval_hz <= 0:
            raise ValueError(f"expected_eval_hz must be >0, got {expected_eval_hz}")
        self._max_window_ms = max_window_ms
        maxlen = int(max_window_ms / 1000 * expected_eval_hz * 1.5) + 1
        self._buf: deque[FrozenFacts] = deque(maxlen=maxlen)

    @property
    def max_window_ms(self) -> int:
        return self._max_window_ms

    def __len__(self) -> int:
        return len(self._buf)

    def append(self, frame: FrozenFacts) -> None:
        """单写入口. 按 recv_ts_ms 单调升序."""
        if self._buf and frame.recv_ts_ms < self._buf[-1].recv_ts_ms:
            raise ValueError(
                f"FactsRing.append: out-of-order frame "
                f"({frame.recv_ts_ms} < last {self._buf[-1].recv_ts_ms})"
            )
        self._buf.append(frame)

    def latest(self) -> FrozenFacts | None:
        return self._buf[-1] if self._buf else None

    def slice(self, window_ms: int) -> Sequence[FrozenFacts]:
        """最近 window_ms 内的帧."""
        if window_ms <= 0 or not self._buf:
            return ()
        window_ms = min(window_ms, self._max_window_ms)
        latest_ts = self._buf[-1].recv_ts_ms
        cutoff = latest_ts - window_ms
        snapshot = list(self._buf)
        keys = [f.recv_ts_ms for f in snapshot]
        i = bisect.bisect_left(keys, cutoff)
        return tuple(snapshot[i:])

    def clear(self) -> None:
        self._buf.clear()
