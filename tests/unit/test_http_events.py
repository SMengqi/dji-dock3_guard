"""Stage 2 B3: EventBus pub-sub + /events SSE 单测.

streaming 测试用 httpx.AsyncClient + ASGITransport: 整个流走同一个 asyncio
event loop, 避免 TestClient 跨线程往 asyncio.Queue put 的非线程安全问题.
"""

from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient

from dock_guard.http.app import build_app
from dock_guard.http.events import EventBus, _format_sse
from dock_guard.http.state import HttpState

# ─── EventBus 行为 ────────────────────────────────────────────────


class TestEventBus:
    async def test_publish_without_subscriber_noop(self) -> None:
        bus = EventBus()
        bus.publish("alert", {"x": 1})
        assert bus.subscriber_count == 0

    async def test_subscribe_then_publish_then_receive(self) -> None:
        bus = EventBus()
        async with bus.subscribe() as q:
            bus.publish("alert", {"code": "X"})
            item = await asyncio.wait_for(q.get(), timeout=1.0)
            assert item == ("alert", {"code": "X"})

    async def test_subscribe_exits_unregisters(self) -> None:
        bus = EventBus()
        async with bus.subscribe():
            assert bus.subscriber_count == 1
        assert bus.subscriber_count == 0

    async def test_fanout_to_two_subscribers(self) -> None:
        bus = EventBus()
        async with bus.subscribe() as q1:
            async with bus.subscribe() as q2:
                bus.publish("phase_transition", {"p": "PREFLIGHT"})
                a = await asyncio.wait_for(q1.get(), timeout=1.0)
                b = await asyncio.wait_for(q2.get(), timeout=1.0)
                assert a == ("phase_transition", {"p": "PREFLIGHT"})
                assert b == ("phase_transition", {"p": "PREFLIGHT"})

    async def test_slow_subscriber_dropped_on_overflow(self) -> None:
        """maxsize=256: 灌 257 条不消费, 第 257 条触发 drop -> 队列入 None sentinel."""
        bus = EventBus()
        async with bus.subscribe() as q:
            for i in range(256):
                bus.publish("alert", {"i": i})
            assert q.qsize() == 256
            # 第 257 条: 队列满 -> drop 该 subscriber.
            bus.publish("alert", {"i": 256})
            assert bus.subscriber_count == 0


class TestFormatSse:
    def test_basic_frame(self) -> None:
        out = _format_sse("alert", {"code": "PREFLIGHT_X"})
        assert out.startswith("event: alert\n")
        assert "data: " in out
        assert out.endswith("\n\n")
        data_line = next(ln for ln in out.split("\n") if ln.startswith("data: "))
        assert json.loads(data_line[6:]) == {"code": "PREFLIGHT_X"}

    def test_unicode_preserved(self) -> None:
        """ensure_ascii=False 保留中文; 现场卡片信息含中文."""
        out = _format_sse("alert", {"msg": "急停按下"})
        assert "急停按下" in out


# ─── SSE 路由鉴权 + 流式行为 ──────────────────────────────────────


def _make_client(token: str = "tt") -> tuple[TestClient, EventBus]:
    bus = EventBus()
    state = HttpState(
        admin_token=token,
        mqtt_connected=True,
        seen_first_osd=True,
        event_bus=bus,
    )
    return TestClient(build_app(state)), bus


class TestEventsRoute:
    def test_events_requires_token(self) -> None:
        client, _ = _make_client(token="right")
        resp = client.get("/events")
        assert resp.status_code == 401

    # 真实流式 e2e (publish -> SSE 帧到客户端 + content-type 头) 留 B5,
    # 在 uvicorn 真起服务后用 curl / httpx 端到端跑.
    # TestClient + SSE: 生成器需 keepalive timeout (15s) 才检测断连, 单测里会卡.
