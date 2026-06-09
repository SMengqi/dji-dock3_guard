"""Aggregator 层 (Phase 3).

设计 §4 + §5.2.1:
- DockAggregator: 单 dock+drone 的状态中心. apply(envelope) 是唯一写入口.
- FrozenFacts:    每帧 fact 快照, 不可变.
- FactsRing:      单写多读环形 buffer, custom_fn 只读切片.
- TimeBoundedDeque: 时间窗口派生量 (wind_gust_max_30s 等).
- phase_machine:  §4.3.1 / §4.3.2 二维表 + mode_code 降级.

下游 (rules / coordinator) 只读 facts, 不直接读 Aggregator 内部.
"""

from dock_guard.aggregator.dock_aggregator import DockAggregator, PhaseTransition
from dock_guard.aggregator.facts import F, FrozenFacts, freeze_facts
from dock_guard.aggregator.facts_ring import FactsRing
from dock_guard.aggregator.phase_machine import resolve_phase
from dock_guard.aggregator.windows import TimeBoundedDeque

__all__ = [
    "DockAggregator",
    "F",
    "FactsRing",
    "FrozenFacts",
    "PhaseTransition",
    "TimeBoundedDeque",
    "freeze_facts",
    "resolve_phase",
]
