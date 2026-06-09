"""Phase 3 单元测试: FrozenFacts + FactsRing (设计 §5.2.1)."""

from __future__ import annotations

import pytest

from dock_guard.aggregator.facts import freeze_facts
from dock_guard.aggregator.facts_ring import FactsRing


class TestFrozenFacts:
    def test_immutable_inner_dict(self) -> None:
        f = freeze_facts(1000, {"a": 1, "b": "x"})
        with pytest.raises(TypeError):
            f.facts["a"] = 99  # type: ignore[index]

    def test_outer_dataclass_frozen(self) -> None:
        f = freeze_facts(1000, {"a": 1})
        with pytest.raises(AttributeError):
            f.recv_ts_ms = 2000  # type: ignore[misc]

    def test_post_freeze_source_mutation_isolated(self) -> None:
        src = {"a": 1}
        f = freeze_facts(1000, src)
        src["a"] = 999
        assert f.facts["a"] == 1


class TestFactsRing:
    def test_append_and_latest(self) -> None:
        ring = FactsRing(max_window_ms=10000)
        assert ring.latest() is None
        ring.append(freeze_facts(100, {"x": 1}))
        ring.append(freeze_facts(200, {"x": 2}))
        latest = ring.latest()
        assert latest is not None
        assert latest.recv_ts_ms == 200

    def test_out_of_order_append_rejected(self) -> None:
        ring = FactsRing(max_window_ms=10000)
        ring.append(freeze_facts(200, {}))
        with pytest.raises(ValueError, match="out-of-order"):
            ring.append(freeze_facts(100, {}))

    def test_slice_basic(self) -> None:
        ring = FactsRing(max_window_ms=10000)
        for ts in (1000, 1500, 2000, 2500, 3000):
            ring.append(freeze_facts(ts, {"ts": ts}))
        s = ring.slice(window_ms=1000)
        assert [f.recv_ts_ms for f in s] == [2000, 2500, 3000]

    def test_slice_clamped_to_max_window(self) -> None:
        ring = FactsRing(max_window_ms=1000)
        for ts in (100, 500, 900, 1500, 2000):
            ring.append(freeze_facts(ts, {}))
        s = ring.slice(window_ms=10000)
        assert [f.recv_ts_ms for f in s] == [1500, 2000]

    def test_slice_empty_ring(self) -> None:
        ring = FactsRing(max_window_ms=10000)
        assert ring.slice(1000) == ()

    def test_clear(self) -> None:
        ring = FactsRing(max_window_ms=10000)
        ring.append(freeze_facts(100, {}))
        ring.clear()
        assert ring.latest() is None
        assert len(ring) == 0

    def test_invalid_params(self) -> None:
        with pytest.raises(ValueError):
            FactsRing(max_window_ms=0)
        with pytest.raises(ValueError):
            FactsRing(max_window_ms=10000, expected_eval_hz=0)

    def test_slice_returns_tuple(self) -> None:
        ring = FactsRing(max_window_ms=10000)
        ring.append(freeze_facts(100, {}))
        s = ring.slice(1000)
        assert isinstance(s, tuple)
