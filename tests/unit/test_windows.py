"""Phase 3 单元测试: TimeBoundedDeque (设计 §4.5)."""

from __future__ import annotations

import pytest

from dock_guard.aggregator.windows import TimeBoundedDeque


class TestTimeBoundedDeque:
    def test_basic_push_and_max(self) -> None:
        w = TimeBoundedDeque(window_ms=30000)
        w.push(1000, 5.0)
        w.push(2000, 12.0)
        w.push(3000, 3.0)
        assert w.max() == 12.0
        assert len(w) == 3

    def test_window_eviction(self) -> None:
        w = TimeBoundedDeque(window_ms=30000)
        w.push(0, 100.0)
        w.push(5000, 50.0)
        w.push(40000, 10.0)
        assert w.max() == 10.0
        assert len(w) == 1

    def test_out_of_order_dropped(self) -> None:
        w = TimeBoundedDeque(window_ms=30000)
        w.push(2000, 5.0)
        w.push(1000, 100.0)
        assert w.max() == 5.0

    def test_empty_max_is_none(self) -> None:
        w = TimeBoundedDeque(window_ms=30000)
        assert w.max() is None
        assert w.latest() is None

    def test_invalid_window(self) -> None:
        with pytest.raises(ValueError):
            TimeBoundedDeque(window_ms=0)

    def test_clear(self) -> None:
        w = TimeBoundedDeque(window_ms=30000)
        w.push(1000, 5.0)
        w.clear()
        assert len(w) == 0
        assert w.max() is None
