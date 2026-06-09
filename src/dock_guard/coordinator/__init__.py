"""AlertCoordinator 层 (Phase 5).

设计 §6:
- handle 每条 Verdict 走 cooldown → dedup → mute 三闸, 产出 AlertRecord.
- 同 tick 多 verdict 按 §6.6 排序 (level 降序, code 字典序).
- 不投递通道 (Phase 6 实现), 仅落 alerts.jsonl + 触发 NotificationBus.
"""

from dock_guard.coordinator.alert_record import AlertRecord, Decision
from dock_guard.coordinator.cooldown import CooldownGate
from dock_guard.coordinator.coordinator import (
    AlertCoordinator,
    AlertSink,
    JsonlAlertSink,
    NullAlertSink,
)
from dock_guard.coordinator.dedup import DedupGate, DedupStatus
from dock_guard.coordinator.mute import MuteEntry, MuteState

__all__ = [
    "AlertCoordinator",
    "AlertRecord",
    "AlertSink",
    "CooldownGate",
    "Decision",
    "DedupGate",
    "DedupStatus",
    "JsonlAlertSink",
    "MuteEntry",
    "MuteState",
    "NullAlertSink",
]
