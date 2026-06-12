"""Stage 2 HTTP state: 装载下游对象引用 + readiness 标志 (设计 §9.3 / §7.2).

mutable 设计: ingest 循环负责把 mqtt_connected / seen_first_osd 翻起来,
/readyz 根据这两个标志 + replay_mode 判 200/503.

event_bus: B3 起的 SSE pub-sub; None 表示禁用 /events 路由.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dock_guard.coordinator import AlertCoordinator
    from dock_guard.http.events import EventBus
    from dock_guard.rules import RuleEngine


@dataclass
class HttpState:
    admin_token: str
    mqtt_connected: bool = False
    seen_first_osd: bool = False
    replay_mode: bool = False
    event_bus: EventBus | None = None
    # B4 admin endpoints 需要回写这三个引用; _run_live 构造完
    # coordinator / engine 后赋值, 早期 None 不影响 HTTP 启动.
    coordinator: AlertCoordinator | None = None
    engine: RuleEngine | None = None
    config_dir: Path | None = None
