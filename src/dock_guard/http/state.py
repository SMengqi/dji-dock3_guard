"""Stage 2 HTTP state: 装载下游对象引用 + readiness 标志 (设计 §9.3).

mutable 设计: ingest 循环负责把 mqtt_connected / seen_first_osd 翻起来,
/readyz 根据这两个标志 + replay_mode 判 200/503.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HttpState:
    admin_token: str
    mqtt_connected: bool = False
    seen_first_osd: bool = False
    replay_mode: bool = False
