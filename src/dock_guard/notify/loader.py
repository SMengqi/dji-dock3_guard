"""通道配置加载 (设计 §7.5 / §7.6 / §15.4)."""

from __future__ import annotations

import pathlib
from collections.abc import Mapping
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from dock_guard.config import expand_env_vars
from dock_guard.types import ChannelKind


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ── dingtalk_robots.yaml ────────────────────────────────────────────


class DingTalkCodeFilter(_Strict):
    include: list[str] = Field(default_factory=lambda: ["*"])
    exclude: list[str] = Field(default_factory=list)


class DingTalkRobot(_Strict):
    id: str = Field(min_length=1)
    webhook_url: str = Field(min_length=1)
    secret: str = Field(min_length=1)
    min_severity: Literal["EMERGENCY", "BLOCK", "RETURN", "WARN", "INFO"] = "RETURN"
    rate_limit_per_min: int = Field(default=18, ge=1, le=20)
    repeat_emergency: bool = True
    at_all_on_emergency: bool = True
    at_mobiles_on_emergency: list[str] = Field(default_factory=list)
    code_filter: DingTalkCodeFilter = DingTalkCodeFilter()


class DingTalkRobotsYaml(_Strict):
    version: Literal[1]
    robots: list[DingTalkRobot] = Field(default_factory=list)


# ── webhooks.yaml ───────────────────────────────────────────────────


class WebhookCodeFilter(_Strict):
    include: list[str] = Field(default_factory=lambda: ["*"])
    exclude: list[str] = Field(default_factory=list)


class WebhookRetry(_Strict):
    max_attempts: int = Field(default=3, ge=1)
    backoff_ms: list[int] = Field(default_factory=lambda: [2000, 8000, 30000])


class WebhookEndpoint(_Strict):
    id: str = Field(min_length=1)
    url: str = Field(min_length=1)
    secret: str = Field(min_length=1)
    min_severity: Literal["EMERGENCY", "BLOCK", "RETURN", "WARN", "INFO"] = "RETURN"
    code_filter: WebhookCodeFilter = WebhookCodeFilter()
    timeout_ms: int = Field(default=5000, ge=100)
    retry: WebhookRetry = WebhookRetry()


class WebhooksYaml(_Strict):
    version: Literal[1]
    endpoints: list[WebhookEndpoint] = Field(default_factory=list)


# ── notification_routing.yaml ───────────────────────────────────────


class RoutingOverride(_Strict):
    channels: list[ChannelKind] = Field(default_factory=list)
    dingtalk_robots: list[str] = Field(default_factory=list)
    webhook_endpoints: list[str] = Field(default_factory=list)


class NotificationRoutingYaml(_Strict):
    version: Literal[1]
    overrides: Mapping[str, RoutingOverride] = Field(default_factory=dict)


# ── loaders ─────────────────────────────────────────────────────────


def _load_yaml_with_env(path: pathlib.Path, env: Mapping[str, str] | None = None) -> object:
    if not path.exists():
        raise FileNotFoundError(path)
    raw = path.read_text(encoding="utf-8")
    expanded = expand_env_vars(raw, env, yaml_path=path)
    return yaml.safe_load(expanded)


def load_dingtalk_robots(
    path: pathlib.Path, env: Mapping[str, str] | None = None
) -> DingTalkRobotsYaml:
    return DingTalkRobotsYaml.model_validate(_load_yaml_with_env(path, env))


def load_webhooks(
    path: pathlib.Path, env: Mapping[str, str] | None = None
) -> WebhooksYaml:
    return WebhooksYaml.model_validate(_load_yaml_with_env(path, env))


def load_notification_routing(path: pathlib.Path) -> NotificationRoutingYaml:
    return NotificationRoutingYaml.model_validate(_load_yaml_with_env(path))
