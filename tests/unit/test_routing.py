"""Phase 6 单元测试: Router (设计 §7.3 + §15.4)."""

from __future__ import annotations

from types import MappingProxyType

from dock_guard.config import AlertLevelsYaml, CoordinatorParams, LevelRouting
from dock_guard.notify.loader import NotificationRoutingYaml, RoutingOverride
from dock_guard.notify.notification import Notification
from dock_guard.notify.routing import Router
from dock_guard.types import ChannelKind, Severity


def _alert_levels() -> AlertLevelsYaml:
    return AlertLevelsYaml(
        version=2,
        level_routing_defaults={
            "emergency": LevelRouting(channels=[ChannelKind.PANEL, ChannelKind.WEBHOOK,
                                                ChannelKind.DINGTALK]),
            "block": LevelRouting(channels=[ChannelKind.PANEL, ChannelKind.WEBHOOK,
                                            ChannelKind.DINGTALK]),
            "return": LevelRouting(channels=[ChannelKind.PANEL, ChannelKind.WEBHOOK,
                                             ChannelKind.DINGTALK]),
            "warn": LevelRouting(channels=[ChannelKind.PANEL, ChannelKind.WEBHOOK]),
            "info": LevelRouting(channels=[ChannelKind.PANEL]),
        },
        coordinator=CoordinatorParams(),
    )


def _notif(severity: Severity, code: str = "TEST") -> Notification:
    return Notification(
        id="notif_abc",
        ts_ms=1,
        source="rule_verdict",
        severity=severity,
        code=code,
        title="X",
        summary="X",
        context=MappingProxyType({}),
        suggested_action="notify",
        dedup_key="X",
    )


class TestSeverityDefaults:
    def test_emergency_all_channels(self) -> None:
        r = Router(_alert_levels())
        channels = r.channels_for(_notif(Severity.EMERGENCY))
        assert ChannelKind.PANEL in channels
        assert ChannelKind.WEBHOOK in channels
        assert ChannelKind.DINGTALK in channels

    def test_info_only_panel(self) -> None:
        r = Router(_alert_levels())
        channels = r.channels_for(_notif(Severity.INFO))
        assert channels == [ChannelKind.PANEL]

    def test_warn_no_dingtalk(self) -> None:
        r = Router(_alert_levels())
        channels = r.channels_for(_notif(Severity.WARN))
        assert ChannelKind.DINGTALK not in channels


class TestCodeOverride:
    def test_override_replaces_severity(self) -> None:
        routing = NotificationRoutingYaml(
            version=1,
            overrides={"NOISY": RoutingOverride(channels=[ChannelKind.PANEL])},
        )
        r = Router(_alert_levels(), routing)
        channels = r.channels_for(_notif(Severity.EMERGENCY, code="NOISY"))
        assert channels == [ChannelKind.PANEL]

    def test_no_override_uses_severity(self) -> None:
        routing = NotificationRoutingYaml(
            version=1,
            overrides={"OTHER_CODE": RoutingOverride(channels=[ChannelKind.PANEL])},
        )
        r = Router(_alert_levels(), routing)
        channels = r.channels_for(_notif(Severity.EMERGENCY, code="UNRELATED"))
        assert ChannelKind.DINGTALK in channels

    def test_dingtalk_robot_override(self) -> None:
        routing = NotificationRoutingYaml(
            version=1,
            overrides={"X": RoutingOverride(
                channels=[ChannelKind.DINGTALK],
                dingtalk_robots=["ops-primary", "on-call"]
            )},
        )
        r = Router(_alert_levels(), routing)
        ids = r.dingtalk_robot_ids_for(_notif(Severity.RETURN, code="X"))
        assert ids == ["ops-primary", "on-call"]
