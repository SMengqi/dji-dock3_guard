"""Phase 7 单元测试: MqttSource (设计 §3.1)."""

from __future__ import annotations

import asyncio
import json
import pathlib
import textwrap
from collections.abc import AsyncIterator
from typing import Any

import aiomqtt
import pytest

from dock_guard.config import AppConfig, load_app_config
from dock_guard.ingest.mqtt_source import MqttSource
from dock_guard.types import TopicKey

# ─── Fake aiomqtt.Client ────────────────────────────────────────────


class FakeMessage:
    def __init__(self, topic: str, payload: dict[str, Any]) -> None:
        self.topic = topic
        self.payload = json.dumps(payload).encode("utf-8")


class FakeMqttClient:
    def __init__(
        self,
        messages: list[FakeMessage] | None = None,
        *,
        raise_on_enter: Exception | None = None,
    ) -> None:
        self._messages = list(messages or [])
        self.subscriptions: list[tuple[str, int]] = []
        self._raise_enter = raise_on_enter

    async def __aenter__(self) -> FakeMqttClient:
        if self._raise_enter is not None:
            raise self._raise_enter
        return self

    async def __aexit__(self, *a: object) -> None:
        return None

    async def subscribe(self, topic: str, qos: int = 0) -> None:
        self.subscriptions.append((topic, qos))

    @property
    def messages(self) -> AsyncIterator[FakeMessage]:
        async def _gen() -> AsyncIterator[FakeMessage]:
            for m in self._messages:
                yield m
        return _gen()


# ─── 共享 fixture ──────────────────────────────────────────────────


def _make_cfg(tmp_path: pathlib.Path, dock_sn: str = "DOCK1") -> AppConfig:
    repo_config_dir = pathlib.Path(__file__).resolve().parents[2] / "config"
    if not (repo_config_dir / "mode_code_map.yaml").exists():
        pytest.skip("repo config not present")
    for name in ("mode_code_map.yaml", "alert_levels.yaml", "enums.yaml"):
        (tmp_path / name).symlink_to(repo_config_dir / name)
    (tmp_path / "runtime.yaml").write_text(textwrap.dedent(f"""
        schema_version: 1
        mqtt:
          broker_url:  ${{MQTT_BROKER_URL}}
          username:    ${{MQTT_USERNAME}}
          password:    ${{MQTT_PASSWORD}}
          qos: 1
          reconnect:
            initial_delay_s: 1
            max_delay_s: 60
            factor: 2
        subscriptions:
          - dock_sn: {dock_sn}
            enabled: true
    """))
    return load_app_config(tmp_path, env={
        "MQTT_BROKER_URL": "ssl://test:8883",
        "MQTT_USERNAME": "u", "MQTT_PASSWORD": "p",
    }, with_rules=False)


# ─── 订阅清单 ──────────────────────────────────────────────────────


class TestSubscriptionPlan:
    async def test_dock_topics_subscribed_at_startup(
        self, tmp_path: pathlib.Path
    ) -> None:
        cfg = _make_cfg(tmp_path, dock_sn="8UU1")
        fake = FakeMqttClient()
        src = MqttSource(cfg, client_factory=lambda: fake)

        async for _ in src:
            pytest.fail("no messages expected")

        subs = [t for t, _ in fake.subscriptions]
        assert "thing/product/8UU1/osd" in subs
        assert "thing/product/8UU1/state" in subs
        assert "thing/product/8UU1/events" in subs
        assert "sys/product/8UU1/status" in subs
        # drone_* 未在 drone_sn 发现前不应被订阅
        assert not any("/state_reply" in t for t in subs)
        # drc_up 默认关
        assert not any("drc/up" in t for t in subs)


# ─── 动态 drone_sn 发现 ────────────────────────────────────────────


class TestDroneSnDiscovery:
    async def test_drone_sn_discovered_from_dock_osd(
        self, tmp_path: pathlib.Path
    ) -> None:
        cfg = _make_cfg(tmp_path, dock_sn="8UU1")
        dock_osd = FakeMessage(
            "thing/product/8UU1/osd",
            {"data": {"sub_device": {"device_sn": "DRONE_X"}}, "timestamp": 1700000000000},
        )
        fake = FakeMqttClient([dock_osd])
        src = MqttSource(cfg, client_factory=lambda: fake)
        envs = []
        async for env in src:
            envs.append(env)

        assert len(envs) == 1
        subs_after = [t for t, _ in fake.subscriptions]
        assert "thing/product/DRONE_X/osd" in subs_after
        assert "thing/product/DRONE_X/events" in subs_after

    async def test_drone_sn_not_discovered_no_subscribe(
        self, tmp_path: pathlib.Path
    ) -> None:
        cfg = _make_cfg(tmp_path, dock_sn="8UU1")
        dock_osd = FakeMessage(
            "thing/product/8UU1/osd",
            {"data": {"flighttask_step_code": 5}, "timestamp": 1},
        )
        fake = FakeMqttClient([dock_osd])
        src = MqttSource(cfg, client_factory=lambda: fake)
        async for _ in src:
            pass
        subs = [t for t, _ in fake.subscriptions]
        assert not any("DRONE" in t for t in subs)


# ─── Envelope 构造 ────────────────────────────────────────────────


class TestBuildEnvelope:
    async def test_dock_osd_envelope(self, tmp_path: pathlib.Path) -> None:
        cfg = _make_cfg(tmp_path, dock_sn="8UU1")
        msg = FakeMessage("thing/product/8UU1/osd",
                          {"data": {"foo": "bar"}, "timestamp": 1700000000000})
        fake = FakeMqttClient([msg])
        src = MqttSource(cfg, client_factory=lambda: fake)
        envs = []
        async for env in src:
            envs.append(env)

        assert len(envs) == 1
        e = envs[0]
        assert e.topic_key == TopicKey.DOCK_OSD
        assert e.dock_sn == "8UU1"
        assert e.drone_sn is None
        assert e.direction == "up"
        assert e.dji_ts_ms == 1700000000000

    async def test_invalid_json_payload_skipped(self, tmp_path: pathlib.Path) -> None:
        cfg = _make_cfg(tmp_path, dock_sn="8UU1")
        bad = FakeMessage("thing/product/8UU1/osd", {})
        bad.payload = b"not-json"
        good = FakeMessage("thing/product/8UU1/osd",
                           {"data": {"x": 1}, "timestamp": 1})
        fake = FakeMqttClient([bad, good])
        src = MqttSource(cfg, client_factory=lambda: fake)
        envs = []
        async for env in src:
            envs.append(env)
        assert len(envs) == 1

    async def test_unknown_topic_skipped(self, tmp_path: pathlib.Path) -> None:
        cfg = _make_cfg(tmp_path, dock_sn="8UU1")
        unknown = FakeMessage("thing/product/8UU1/events_reply",
                              {"data": {}, "timestamp": 1})
        fake = FakeMqttClient([unknown])
        src = MqttSource(cfg, client_factory=lambda: fake)
        envs = []
        async for env in src:
            envs.append(env)
        assert envs == []


# ─── 重连 ─────────────────────────────────────────────────────────


class TestReconnect:
    async def test_reconnect_on_mqtt_error(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = _make_cfg(tmp_path, dock_sn="8UU1")
        attempts: list[int] = []
        good_msg = FakeMessage("thing/product/8UU1/osd",
                                {"data": {"x": 1}, "timestamp": 1})

        def factory() -> Any:
            attempts.append(len(attempts))
            if len(attempts) == 1:
                return FakeMqttClient(raise_on_enter=aiomqtt.MqttError("first fail"))
            return FakeMqttClient([good_msg])

        # 跳过 sleep 加速测试
        async def no_sleep(t: float) -> None:
            return None
        monkeypatch.setattr(asyncio, "sleep", no_sleep)

        src = MqttSource(cfg, client_factory=factory)
        envs = []
        async for env in src:
            envs.append(env)
            break

        assert len(attempts) == 2
        assert len(envs) == 1
