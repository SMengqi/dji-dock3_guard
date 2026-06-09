"""Envelope 与 Source 抽象 (设计 §3.4).

Envelope: 单条 MQTT 上行消息, 字段镜像 sim_dji_cloud_service 的 jsonl 格式.
Source:   异步迭代器协议, 实时和回放共用.
parse_topic: 由 topic 字符串反解出 TopicKey + dock_sn + drone_sn (静态映射,无状态).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from dock_guard.types import DRONE_SN_TOPICS, TOPIC_TEMPLATES, TopicKey


@dataclass(frozen=True, slots=True)
class Envelope:
    """单条 MQTT envelope.

    与录制目录的 jsonl 格式严格对齐 (设计 §0.4):
        {recv_ts_ms, dji_ts_ms, direction, topic, payload}

    `topic_key` / `dock_sn` / `drone_sn` 由 ingest 层在构造时填入派生字段,
    下游不需要重新解析 topic 字符串.
    """

    recv_ts_ms: int
    dji_ts_ms: int | None    # services_reply / drc/down 等可能为 null;
                             # 设计 §10.2: 不参与规则评估, 仅审计用
    direction: str          # "up" / "down" / "svc_rsp"
    topic: str              # 实际 MQTT topic
    payload: Mapping[str, Any]

    # 派生
    topic_key: TopicKey
    dock_sn: str
    drone_sn: str | None     # 仅 drone_* 类 topic 才非 None


@runtime_checkable
class Source(Protocol):
    """ingest source 协议: 异步可迭代 Envelope 流, 可显式关闭.

    实时 MqttSource 和离线 ReplaySource 均实现此协议, 下游管线无须区分.
    """

    def __aiter__(self) -> AsyncIterator[Envelope]: ...

    async def close(self) -> None:
        """释放资源 (关闭 MQTT 连接 / 关闭文件句柄). 多次调用安全."""
        ...


def parse_topic(
    topic: str,
    *,
    dock_sn: str,
    drone_sn: str | None,
) -> tuple[TopicKey, str, str | None] | None:
    """根据已知 dock_sn / drone_sn, 反解 topic 字符串.

    返回 (topic_key, dock_sn, drone_sn_or_none) 或 None (topic 不匹配任何已知模板).

    drone_sn 未知 (例如 dock 首帧 OSD 之前) 时, drone_* 类 topic 永远返回 None
    —— ingest 层应延后这些 topic 的订阅 (设计 §15.1.1 硬约束 #3).
    """
    drone_placeholder = drone_sn if drone_sn is not None else "\x00<DRONE_SN_UNKNOWN>"
    for key, template in TOPIC_TEMPLATES.items():
        if key in DRONE_SN_TOPICS and drone_sn is None:
            continue
        substituted = template.format(dock_sn=dock_sn, drone_sn=drone_placeholder)
        if substituted == topic:
            ds = drone_sn if key in DRONE_SN_TOPICS else None
            return key, dock_sn, ds
    return None
