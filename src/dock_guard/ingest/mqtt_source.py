"""MqttSource — aiomqtt 异步订阅 broker (设计 §3.1).

设计原则:
- **仅 SUBSCRIBE, 永不 PUBLISH 到 thing/+/services** (设计 §0.2 + §12.4 CI 硬约束).
- aiomqtt Client 自带连接管理; 我方加重连指数退避.
- 动态 drone_sn 发现: dock OSD 首帧 sub_device.device_sn → 触发 drone_* 订阅.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import ssl
import time
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from typing import Any
from urllib.parse import urlparse

import aiomqtt

from dock_guard.config import AppConfig
from dock_guard.ingest.source import Envelope, parse_topic
from dock_guard.types import DRONE_SN_TOPICS, TOPIC_TEMPLATES, TopicKey

logger = logging.getLogger(__name__)


class MqttSource:
    """实现 Source 协议."""

    def __init__(
        self,
        cfg: AppConfig,
        *,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.cfg = cfg
        self._client_factory = client_factory or self._default_client_factory

        self._dock_topic_maps: dict[str, dict[TopicKey, bool]] = {}
        for sub in cfg.runtime.subscriptions:
            if sub.enabled:
                self._dock_topic_maps[sub.dock_sn] = sub.effective_topics(
                    cfg.runtime.topic_defaults
                )

        self._drone_sn_by_dock: dict[str, str] = {}
        self._stop_event = asyncio.Event()

    # ── Source 协议 ────────────────────────────────────────────────

    async def __aiter__(self) -> AsyncIterator[Envelope]:
        reconnect = self.cfg.runtime.mqtt.reconnect
        delay = reconnect.initial_delay_s

        while not self._stop_event.is_set():
            try:
                async with self._client_factory() as client:
                    await self._subscribe_dock_topics(client)
                    delay = reconnect.initial_delay_s

                    async for msg in client.messages:
                        if self._stop_event.is_set():
                            break
                        env = self._build_envelope(msg)
                        if env is None:
                            continue
                        if env.topic_key == TopicKey.DOCK_OSD:
                            await self._maybe_discover_drone_sn(client, env)
                        yield env
            except aiomqtt.MqttError as e:
                if self._stop_event.is_set():
                    return
                logger.warning("MQTT error: %s; reconnect in %ds", e, delay)
                with suppress(asyncio.CancelledError):
                    await asyncio.sleep(delay)
                delay = min(int(delay * reconnect.factor), reconnect.max_delay_s)
            except asyncio.CancelledError:
                return

    async def close(self) -> None:
        self._stop_event.set()

    # ── 内部 ──────────────────────────────────────────────────────

    def _default_client_factory(self) -> aiomqtt.Client:
        mqtt = self.cfg.runtime.mqtt
        parsed = urlparse(mqtt.broker_url)
        host = parsed.hostname or "localhost"
        scheme = (parsed.scheme or "").lower()
        port = parsed.port or (8883 if scheme in ("ssl", "mqtts") else 1883)

        tls_context: ssl.SSLContext | None = None
        if mqtt.tls.enabled or scheme in ("ssl", "mqtts"):
            tls_context = ssl.create_default_context()
            if mqtt.tls.ca_cert_path:
                tls_context.load_verify_locations(mqtt.tls.ca_cert_path)
            if not mqtt.tls.verify_hostname:
                # 仅关闭主机名匹配, 不动证书链验证 (verify_mode 保持 CERT_REQUIRED).
                # 设计 §10.1 安全口径: 自签证书应通过 ca_cert_path 显式提供 CA,
                # 而不是关闭验证. verify_hostname=false 仅是 hostname/SAN 不匹配时
                # 的临时手段, 仍要求证书链可信.
                tls_context.check_hostname = False

        identifier = f"{mqtt.client_id_prefix}-{socket.gethostname()}-{os.getpid()}"

        return aiomqtt.Client(
            hostname=host,
            port=port,
            # 空串 -> None: aiomqtt / paho 在 None 时不发 CONNECT.user/password
            # (本地 sim mosquitto 默认无 auth 即可走通).
            username=mqtt.username or None,
            password=mqtt.password or None,
            identifier=identifier,
            tls_context=tls_context,
        )

    async def _subscribe_dock_topics(self, client: Any) -> None:
        qos = self.cfg.runtime.mqtt.qos
        for dock_sn, topic_map in self._dock_topic_maps.items():
            for topic_key, enabled in topic_map.items():
                if not enabled:
                    continue
                if topic_key in DRONE_SN_TOPICS:
                    continue
                topic = TOPIC_TEMPLATES[topic_key].format(
                    dock_sn=dock_sn, drone_sn="<NA>"
                )
                await client.subscribe(topic, qos=qos)
                logger.info("subscribed: %s", topic)

    async def _maybe_discover_drone_sn(self, client: Any, env: Envelope) -> None:
        if env.dock_sn in self._drone_sn_by_dock:
            return
        if not isinstance(env.payload, dict):
            return
        data = env.payload.get("data")
        if not isinstance(data, dict):
            return
        sub_device = data.get("sub_device")
        if not isinstance(sub_device, dict):
            return
        drone_sn_raw = sub_device.get("device_sn")
        if not drone_sn_raw or not isinstance(drone_sn_raw, str):
            return

        self._drone_sn_by_dock[env.dock_sn] = drone_sn_raw
        topic_map = self._dock_topic_maps.get(env.dock_sn, {})
        qos = self.cfg.runtime.mqtt.qos
        for topic_key in DRONE_SN_TOPICS:
            if not topic_map.get(topic_key, False):
                continue
            topic = TOPIC_TEMPLATES[topic_key].format(
                dock_sn=env.dock_sn, drone_sn=drone_sn_raw
            )
            await client.subscribe(topic, qos=qos)
            logger.info("subscribed (delayed): %s", topic)

    def _build_envelope(self, msg: Any) -> Envelope | None:
        topic = str(msg.topic)

        try:
            payload_raw = msg.payload
            if isinstance(payload_raw, (bytes, bytearray)):
                payload = json.loads(payload_raw.decode("utf-8"))
            else:
                payload = json.loads(payload_raw)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
            return None

        for dock_sn in self._dock_topic_maps:
            drone_sn = self._drone_sn_by_dock.get(dock_sn)
            parsed = parse_topic(topic, dock_sn=dock_sn, drone_sn=drone_sn)
            if parsed is not None:
                topic_key, ds, dr_sn = parsed
                ts_now_ms = int(time.time() * 1000)
                dji_ts: int | None = None
                if isinstance(payload, dict):
                    raw_ts = payload.get("timestamp")
                    if isinstance(raw_ts, (int, float)):
                        dji_ts = int(raw_ts)
                return Envelope(
                    recv_ts_ms=ts_now_ms,
                    dji_ts_ms=dji_ts,
                    direction="up",
                    topic=topic,
                    payload=payload,
                    topic_key=topic_key,
                    dock_sn=ds,
                    drone_sn=dr_sn,
                )
        return None
