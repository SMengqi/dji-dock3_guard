"""NotificationBus — 路由 + 多通道并发投递 (设计 §7)."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from dock_guard.notify.channel import Channel, ChannelResult
from dock_guard.notify.notification import Notification
from dock_guard.notify.routing import Router
from dock_guard.types import ChannelKind


class NotificationBus:
    def __init__(
        self,
        channels: Mapping[ChannelKind, Channel],
        router: Router,
    ) -> None:
        self.channels = dict(channels)
        self.router = router

    async def dispatch(self, notif: Notification) -> dict[str, dict]:
        targets = self.router.channels_for(notif)
        if not targets:
            return {}

        tasks: list[tuple[ChannelKind, asyncio.Task[ChannelResult]]] = []
        for kind in targets:
            ch = self.channels.get(kind)
            if ch is None:
                continue
            tasks.append((kind, asyncio.create_task(ch.send(notif))))

        results: dict[str, dict] = {}
        for kind, task in tasks:
            try:
                res = await task
                results[kind.value] = res.to_dict()
            except Exception as e:
                results[kind.value] = {
                    "sent": False,
                    "error": type(e).__name__,
                    "message": str(e),
                }
        return results

    async def close(self) -> None:
        for ch in self.channels.values():
            try:
                await ch.close()
            except Exception:
                pass
