"""Phase 6 单元测试: NotificationBus."""

from __future__ import annotations

from types import MappingProxyType
from unittest.mock import AsyncMock

from dock_guard.config import AlertLevelsYaml, CoordinatorParams, LevelRouting
from dock_guard.notify.bus import NotificationBus
from dock_guard.notify.channel import Channel, ChannelResult
from dock_guard.notify.notification import Notification
from dock_guard.notify.routing import Router
from dock_guard.types import ChannelKind, Severity


def _notif(severity: Severity = Severity.RETURN) -> Notification:
    return Notification(
        id="notif_x", ts_ms=1, source="rule_verdict", severity=severity,
        code="TEST", title="T", summary="S",
        context=MappingProxyType({}), suggested_action="notify", dedup_key="X",
    )


def _router_with(channels: list[ChannelKind]) -> Router:
    al = AlertLevelsYaml(
        version=2,
        level_routing_defaults={
            sev: LevelRouting(channels=channels)
            for sev in ("emergency", "block", "return", "warn", "info")
        },
        coordinator=CoordinatorParams(),
    )
    return Router(al)


def _fake_channel(name: str, result: ChannelResult) -> Channel:
    ch = AsyncMock(spec=Channel)
    ch.name = name
    ch.send = AsyncMock(return_value=result)
    ch.close = AsyncMock(return_value=None)
    return ch


class TestNotificationBus:
    async def test_dispatch_to_matching_channels(self) -> None:
        dingtalk = _fake_channel("dingtalk", ChannelResult(sent=True,
                                                            detail={"robots_sent": ["r1"]}))
        webhook = _fake_channel("webhook", ChannelResult(sent=True,
                                                          detail={"endpoints_sent": ["e1"]}))
        bus = NotificationBus(
            {ChannelKind.DINGTALK: dingtalk, ChannelKind.WEBHOOK: webhook},
            _router_with([ChannelKind.DINGTALK, ChannelKind.WEBHOOK]),
        )
        result = await bus.dispatch(_notif())

        assert result["dingtalk"]["sent"] is True
        assert result["webhook"]["sent"] is True
        dingtalk.send.assert_awaited_once()
        webhook.send.assert_awaited_once()

    async def test_skip_unconfigured_channel(self) -> None:
        webhook = _fake_channel("webhook", ChannelResult(sent=True))
        bus = NotificationBus(
            {ChannelKind.WEBHOOK: webhook},
            _router_with([ChannelKind.DINGTALK, ChannelKind.WEBHOOK]),
        )
        result = await bus.dispatch(_notif())

        assert "dingtalk" not in result
        assert "webhook" in result

    async def test_channel_exception_isolated(self) -> None:
        async def boom(n: Notification) -> ChannelResult:
            raise RuntimeError("boom")

        bad = AsyncMock(spec=Channel)
        bad.name = "dingtalk"
        bad.send = boom
        good = _fake_channel("webhook", ChannelResult(sent=True))

        bus = NotificationBus(
            {ChannelKind.DINGTALK: bad, ChannelKind.WEBHOOK: good},
            _router_with([ChannelKind.DINGTALK, ChannelKind.WEBHOOK]),
        )
        result = await bus.dispatch(_notif())

        assert result["dingtalk"]["sent"] is False
        assert "error" in result["dingtalk"]
        assert result["webhook"]["sent"] is True

    async def test_no_channels_for_empty_routing(self) -> None:
        bus = NotificationBus({}, _router_with([]))
        result = await bus.dispatch(_notif())
        assert result == {}
