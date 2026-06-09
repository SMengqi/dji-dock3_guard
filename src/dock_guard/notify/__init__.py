"""通知层 (Phase 6)."""

from dock_guard.notify.bus import NotificationBus
from dock_guard.notify.channel import Channel, ChannelResult
from dock_guard.notify.dingtalk import DingTalkChannel, sign_dingtalk_url
from dock_guard.notify.loader import (
    DingTalkRobot,
    DingTalkRobotsYaml,
    NotificationRoutingYaml,
    WebhookEndpoint,
    WebhooksYaml,
    load_dingtalk_robots,
    load_notification_routing,
    load_webhooks,
)
from dock_guard.notify.notification import Notification
from dock_guard.notify.routing import Router
from dock_guard.notify.webhook import WebhookChannel

__all__ = [
    "Channel",
    "ChannelResult",
    "DingTalkChannel",
    "DingTalkRobot",
    "DingTalkRobotsYaml",
    "Notification",
    "NotificationBus",
    "NotificationRoutingYaml",
    "Router",
    "WebhookChannel",
    "WebhookEndpoint",
    "WebhooksYaml",
    "load_dingtalk_robots",
    "load_notification_routing",
    "load_webhooks",
    "sign_dingtalk_url",
]
