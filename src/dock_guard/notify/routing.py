"""路由器: 根据 severity + code 决定走哪些通道 (设计 §7.3 + §15.4)."""

from __future__ import annotations

from collections.abc import Mapping

from dock_guard.config import AlertLevelsYaml
from dock_guard.notify.loader import NotificationRoutingYaml, RoutingOverride
from dock_guard.notify.notification import Notification
from dock_guard.types import ChannelKind


class Router:
    def __init__(
        self,
        alert_levels: AlertLevelsYaml,
        routing: NotificationRoutingYaml | None = None,
    ) -> None:
        self.alert_levels = alert_levels
        self.overrides: Mapping[str, RoutingOverride] = (
            routing.overrides if routing is not None else {}
        )

    def channels_for(self, notif: Notification) -> list[ChannelKind]:
        override = self.overrides.get(notif.code)
        if override is not None:
            return list(override.channels)
        defaults = self.alert_levels.level_routing_defaults.get(notif.severity.name.lower())
        if defaults is None:
            return []
        return list(defaults.channels)

    def dingtalk_robot_ids_for(self, notif: Notification) -> list[str] | None:
        override = self.overrides.get(notif.code)
        if override is not None and override.dingtalk_robots:
            return list(override.dingtalk_robots)
        return None

    def webhook_endpoint_ids_for(self, notif: Notification) -> list[str] | None:
        override = self.overrides.get(notif.code)
        if override is not None and override.webhook_endpoints:
            return list(override.webhook_endpoints)
        return None
