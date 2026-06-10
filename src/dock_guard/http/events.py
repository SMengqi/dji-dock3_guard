"""Stage 2 B3: Panel SSE (/events) + EventBus 内存 pub-sub.

设计 §7.2: 控制面 SSE 流, 浏览器 EventSource 直连看实时告警 / phase 切换.
本期不做 Last-Event-ID backfill (用户决策: '只推新事件'); 客户端断线重连
只能收到重连之后的事件, 历史靠 alerts.jsonl / phase_transitions.jsonl 翻档.

事件类型:
  event: alert             - AlertCoordinator 处理的每条 AlertRecord (含 SUPPRESSED, 全量审计)
  event: phase_transition  - DockAggregator 输出的每条 PhaseTransition
  : keepalive              - 15s 无事件时一条心跳冒号注释 (维持 HTTP 连接 + 探测断连)

实现: 每个 SSE 客户端独占一个 asyncio.Queue (maxsize=256), publish 时 fan-out;
慢客户端队列满 -> 丢掉 + 强制断开 (浏览器自动重连). 这样防慢客户端拖死整个 bus.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from dock_guard.http.state import HttpState

logger = logging.getLogger(__name__)

_KEEPALIVE_INTERVAL_S = 15.0
_QUEUE_MAXSIZE = 256


class EventBus:
    """内存 pub-sub. 一个进程内一例; publish 同步非阻塞, subscribe 异步迭代.

    线程安全口径: 仅在同 event loop 中调用; 跨 loop 用 loop.call_soon_threadsafe.
    """

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[tuple[str, Any] | None]] = []

    def publish(self, event_type: str, payload: Any) -> None:
        """同步发布. 慢客户端 (队列满) 丢入 sentinel 触发主动断开."""
        if not self._subscribers:
            return
        to_drop: list[asyncio.Queue[tuple[str, Any] | None]] = []
        for q in self._subscribers:
            try:
                q.put_nowait((event_type, payload))
            except asyncio.QueueFull:
                logger.warning(
                    "SSE subscriber queue full (size=%d); dropping subscriber",
                    q.qsize(),
                )
                to_drop.append(q)
        for q in to_drop:
            if q in self._subscribers:
                self._subscribers.remove(q)
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[tuple[str, Any] | None]]:
        """订阅: 进 with 块拿一个 queue; 离开自动注销."""
        q: asyncio.Queue[tuple[str, Any] | None] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        self._subscribers.append(q)
        try:
            yield q
        finally:
            if q in self._subscribers:
                self._subscribers.remove(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


def _format_sse(event_type: str, payload: Any) -> str:
    """W3C EventSource 帧格式: event:\\ndata:\\n\\n. payload 走 JSON."""
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return f"event: {event_type}\ndata: {data}\n\n"


async def _sse_stream(
    bus: EventBus,
    request: Request,
) -> AsyncIterator[str]:
    """单客户端的 SSE 生成器: 队列 get + 心跳 + 断连退出."""
    async with bus.subscribe() as queue:
        try:
            while True:
                try:
                    item = await asyncio.wait_for(
                        queue.get(), timeout=_KEEPALIVE_INTERVAL_S
                    )
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        return
                    yield ": keepalive\n\n"
                    continue
                if item is None:
                    return
                event_type, payload = item
                yield _format_sse(event_type, payload)
        except asyncio.CancelledError:
            return


def register_events(router: APIRouter, state: HttpState) -> None:
    """挂 /events 路由到 router. 调用方负责 router 的 auth dependency."""
    bus = state.event_bus
    if bus is None:
        return

    @router.get("/events")
    async def events(request: Request) -> StreamingResponse:
        return StreamingResponse(
            _sse_stream(bus, request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
