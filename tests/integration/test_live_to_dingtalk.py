"""M1 端到端冒烟测试: 伪 aiomqtt -> MqttSource -> Aggregator -> RuleEngine
-> AlertCoordinator -> NotificationBus -> DingTalkChannel(httpx.MockTransport).

目标: 验证 _run_live 整条投递链路在不联网的前提下能产出钉钉 HTTP 请求,
HMAC 签名正确, Markdown 卡片内容含 verdict code, 且 alerts.jsonl 落 DISPATCHED.

不联网, 不依赖真 broker / 真钉钉, CI 友好.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import pathlib
import textwrap
import urllib.parse
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from dock_guard.__main__ import _build_notification_bus
from dock_guard.aggregator import DockAggregator
from dock_guard.config import load_app_config
from dock_guard.coordinator import AlertCoordinator, Decision, JsonlAlertSink
from dock_guard.ingest.mqtt_source import MqttSource
from dock_guard.notify import DingTalkChannel, NotificationBus, Router
from dock_guard.rules import RuleEngine
from dock_guard.types import ChannelKind


# ── 配置 fixture ──────────────────────────────────────────────────


_M1_ENV = {
    "MQTT_BROKER_URL": "ssl://test:8883",
    "MQTT_USERNAME": "u",
    "MQTT_PASSWORD": "p",
    "DINGTALK_BOT_WEBHOOK_PRIMARY":
        "https://oapi.dingtalk.com/robot/send?access_token=fake-token",
    "DINGTALK_BOT_SECRET_PRIMARY": "SECfakesecret123",
}


def _seed_configs(dst: pathlib.Path, dock_sn: str = "M1_DOCK") -> None:
    repo = pathlib.Path(__file__).resolve().parents[2] / "config"
    if not (repo / "mode_code_map.yaml").exists():
        pytest.skip(f"repo config not present at {repo}")
    for name in ("mode_code_map.yaml", "alert_levels.yaml", "enums.yaml", "rules.yaml"):
        (dst / name).symlink_to(repo / name)
    (dst / "runtime.yaml").write_text(textwrap.dedent(f"""
        schema_version: 1
        mqtt:
          broker_url:  ${{MQTT_BROKER_URL}}
          username:    ${{MQTT_USERNAME}}
          password:    ${{MQTT_PASSWORD}}
        subscriptions:
          - dock_sn: {dock_sn}
            enabled: true
    """))
    (dst / "dingtalk_robots.yaml").write_text(textwrap.dedent("""
        version: 1
        robots:
          - id: ops-primary
            webhook_url: ${DINGTALK_BOT_WEBHOOK_PRIMARY}
            secret:      ${DINGTALK_BOT_SECRET_PRIMARY}
            min_severity: WARN
    """))


# ── 伪 aiomqtt.Client (照搬 test_mqtt_source 的 stop_on_exhaust 模式) ──


class _FakeMessage:
    def __init__(self, topic: str, payload: dict[str, Any]) -> None:
        self.topic = topic
        self.payload = json.dumps(payload).encode("utf-8")


class _FakeMqttClient:
    def __init__(self, messages: list[_FakeMessage]) -> None:
        self._messages = list(messages)
        self.subscriptions: list[tuple[str, int]] = []
        self.stop_on_exhaust: asyncio.Event | None = None

    async def __aenter__(self) -> _FakeMqttClient:
        return self

    async def __aexit__(self, *a: object) -> None:
        return None

    async def subscribe(self, topic: str, qos: int = 0) -> None:
        self.subscriptions.append((topic, qos))

    @property
    def messages(self) -> AsyncIterator[_FakeMessage]:
        async def _gen() -> AsyncIterator[_FakeMessage]:
            for m in self._messages:
                yield m
            if self.stop_on_exhaust is not None:
                self.stop_on_exhaust.set()
        return _gen()


# ── 钉钉 HMAC 复算 (与 dingtalk.py:sign_dingtalk_url 同实现) ─────────


def _expected_sign(secret: str, ts_ms: int) -> str:
    """返回未 URL 编码的 base64 签名 (与 parse_qs 解码后的值对齐).

    钉钉 sign_dingtalk_url 在 URL 中是 quote_plus(b64), 但 urllib.parse.parse_qs
    会自动反解, 这里返回纯 b64 与之比较.
    """
    string_to_sign = f"{ts_ms}\n{secret}"
    code = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(code).decode("utf-8")


# ── 测试 ───────────────────────────────────────────────────────────


async def test_emergency_stop_pressed_drives_dingtalk(tmp_path: pathlib.Path) -> None:
    """灌入 PREFLIGHT 急停按下序列, 断言 DingTalk HTTP 被调用 + 签名正确 +
    alerts.jsonl 落 DISPATCHED."""

    dock_sn = "M1_DOCK"
    drone_sn = "M1_DRONE_X"
    _seed_configs(tmp_path, dock_sn=dock_sn)

    cfg = load_app_config(tmp_path, env=_M1_ENV)
    assert cfg.dingtalk_robots is not None, "B1 加载应让 cfg.dingtalk_robots 非空"
    assert len(cfg.dingtalk_robots.robots) == 1

    # 1) 装配 NotificationBus, 注入 httpx.MockTransport.
    captured: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

    mock_http = httpx.AsyncClient(
        transport=httpx.MockTransport(_handler), timeout=5.0
    )
    dingtalk_ch = DingTalkChannel(list(cfg.dingtalk_robots.robots), http=mock_http)
    bus = NotificationBus(
        {ChannelKind.DINGTALK: dingtalk_ch},
        Router(cfg.alert_levels, cfg.notification_routing),
    )

    # 2) MqttSource + 伪 aiomqtt, 灌一段触发 preflight.emergency_stop_pressed 的序列.
    base_ts = 1700000000000
    msgs = [
        # sys_status: online (sub_type=0 => sys_online=True)
        _FakeMessage(
            f"sys/product/{dock_sn}/status",
            {"sub_type": 0},
        ),
        # dock events: flighttask_progress (设 last_flighttask_progress_ts)
        _FakeMessage(
            f"thing/product/{dock_sn}/events",
            {"method": "flighttask_progress", "data": {"status": "preflight"}},
        ),
        # dock OSD: flighttask_step_code=1 + drone_in_dock=1 + emergency_stop_state=1
        # 含 sub_device.device_sn 触发 drone_sn 发现, 让 drone OSD 主题被订阅.
        _FakeMessage(
            f"thing/product/{dock_sn}/osd",
            {
                "data": {
                    "flighttask_step_code": 1,
                    "drone_in_dock": 1,
                    "emergency_stop_state": 1,
                    "sub_device": {"device_sn": drone_sn},
                },
                "timestamp": base_ts + 100,
            },
        ),
        # drone OSD: mode_code=0 (PREFLIGHT bucket), height=0
        _FakeMessage(
            f"thing/product/{drone_sn}/osd",
            {
                "data": {"mode_code": 0, "height": 0.0},
                "timestamp": base_ts + 200,
            },
        ),
    ]
    fake = _FakeMqttClient(msgs)
    src = MqttSource(cfg, client_factory=lambda: fake)
    fake.stop_on_exhaust = src._stop_event

    # 3) 仿照 _run_live 内循环: ingest -> agg -> rules -> coordinator(handle_batch_async).
    agg = DockAggregator(dock_sn, cfg)
    engine = RuleEngine(cfg.rules, agg)
    alerts_path = tmp_path / "alerts.jsonl"
    coordinator = AlertCoordinator(
        cfg, sink=JsonlAlertSink(alerts_path), bus=bus
    )

    all_records = []
    async for env in src:
        agg.apply(env)
        batch = engine.evaluate()
        if batch:
            records = await coordinator.handle_batch_async(batch)
            all_records.extend(records)

    coordinator.close()
    await bus.close()
    await src.close()

    # ── 断言 1: 钉钉 HTTP 至少被调用一次 ─────────────────────────
    assert captured, (
        f"DingTalk HTTP 未被调用; records={[r.decision.value for r in all_records]}, "
        f"verdicts_codes={[r.verdict.code for r in all_records]}"
    )

    # ── 断言 2: HMAC 签名与 timestamp 同源, 与本地复算一致 ────────
    req = captured[0]
    parsed = urllib.parse.urlparse(str(req.url))
    params = urllib.parse.parse_qs(parsed.query)
    assert "timestamp" in params and "sign" in params, params
    ts_ms = int(params["timestamp"][0])
    received_sign = params["sign"][0]
    expected = _expected_sign(_M1_ENV["DINGTALK_BOT_SECRET_PRIMARY"], ts_ms)
    assert received_sign == expected, (
        f"sign 不一致: got={received_sign} expected={expected}"
    )

    # ── 断言 3: Markdown 卡片含 verdict code + 中文描述 ───────────
    body = json.loads(req.content)
    assert body["msgtype"] == "markdown"
    assert "PREFLIGHT_EMERGENCY_STOP_PRESSED" in body["markdown"]["text"]
    # 标题被中文化为 `[拦阻] 机场急停按钮按下 @<dock_sn>` 形式
    assert body["markdown"]["title"].startswith("[拦阻]")
    assert "机场急停按钮按下" in body["markdown"]["title"]

    # ── 断言 4: alerts.jsonl 落了 DISPATCHED 行, channels.dingtalk.sent=True ──
    assert alerts_path.exists()
    lines = [
        json.loads(line)
        for line in alerts_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    dispatched = [
        r for r in lines
        if r["decision"] == Decision.DISPATCHED.value
        and r["verdict"]["code"] == "PREFLIGHT_EMERGENCY_STOP_PRESSED"
    ]
    assert dispatched, f"alerts.jsonl 无 DISPATCHED 行: {lines}"
    assert dispatched[-1]["channels"].get("dingtalk", {}).get("sent") is True


async def test_no_dingtalk_yaml_degrades_gracefully(tmp_path: pathlib.Path) -> None:
    """没配 dingtalk_robots.yaml 时, _build_notification_bus -> None;
    告警只入 alerts.jsonl, 不应抛 / 不应 hang."""

    repo = pathlib.Path(__file__).resolve().parents[2] / "config"
    if not (repo / "mode_code_map.yaml").exists():
        pytest.skip("repo config not present")
    for name in ("mode_code_map.yaml", "alert_levels.yaml", "enums.yaml", "rules.yaml"):
        (tmp_path / name).symlink_to(repo / name)
    (tmp_path / "runtime.yaml").write_text(textwrap.dedent("""
        schema_version: 1
        mqtt:
          broker_url:  ${MQTT_BROKER_URL}
          username:    ${MQTT_USERNAME}
          password:    ${MQTT_PASSWORD}
        subscriptions:
          - dock_sn: M1_DOCK
            enabled: true
    """))
    # 不写 dingtalk_robots.yaml
    cfg = load_app_config(tmp_path, env={
        "MQTT_BROKER_URL": "ssl://test:8883",
        "MQTT_USERNAME": "u", "MQTT_PASSWORD": "p",
    })
    assert cfg.dingtalk_robots is None

    bus = _build_notification_bus(cfg)
    assert bus is None, "未配钉钉应返回 None"
