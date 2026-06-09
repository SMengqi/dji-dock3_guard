"""Channel 协议与 ChannelResult dataclass."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from dock_guard.notify.notification import Notification


@dataclass(frozen=True, slots=True)
class ChannelResult:
    sent: bool
    detail: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"sent": self.sent, **dict(self.detail)}


@runtime_checkable
class Channel(Protocol):
    @property
    def name(self) -> str: ...

    async def send(self, notif: Notification) -> ChannelResult: ...

    async def close(self) -> None: ...
