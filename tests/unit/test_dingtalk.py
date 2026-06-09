"""Phase 6 单元测试: DingTalk 签名 + 发送 (设计 §7.6)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import urllib.parse
from types import MappingProxyType

import httpx

from dock_guard.notify.dingtalk import (
    DingTalkChannel,
    format_markdown,
    sign_dingtalk_url,
)
from dock_guard.notify.loader import DingTalkRobot
from dock_guard.notify.notification import Notification
from dock_guard.types import Severity


def _notif(severity: Severity = Severity.RETURN, code: str = "TEST") -> Notification:
    return Notification(
        id="notif_abc",
        ts_ms=1780000000000,
        source="rule_verdict",
        severity=severity,
        code=code,
        title=f"[{severity.name}] {code}",
        summary="test summary",
        context=MappingProxyType({"dock_sn": "DOCK1", "phase": "CRUISE"}),
        suggested_action="notify",
        dedup_key=f"r1#{code}",
        verdict_payload={"facts": {"wind": 12.5}, "thresholds": {"wind": ">10"}},
    )


class TestSignDingtalkUrl:
    def test_deterministic(self) -> None:
        u1 = sign_dingtalk_url("https://oapi.dingtalk.com/robot/send?access_token=X",
                                "secret", 1700000000000)
        u2 = sign_dingtalk_url("https://oapi.dingtalk.com/robot/send?access_token=X",
                                "secret", 1700000000000)
        assert u1 == u2

    def test_changes_with_timestamp(self) -> None:
        base = "https://oapi.dingtalk.com/robot/send?access_token=X"
        u1 = sign_dingtalk_url(base, "secret", 1700000000000)
        u2 = sign_dingtalk_url(base, "secret", 1700000000001)
        assert u1 != u2

    def test_signature_matches_manual_hmac(self) -> None:
        secret = "TESTSECRET"
        ts = 1700000000000
        string_to_sign = f"{ts}\n{secret}"
        digest = hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha256).digest()
        expected_sign = urllib.parse.quote_plus(base64.b64encode(digest).decode())
        url = sign_dingtalk_url("https://x.example/robot/send?access_token=A", secret, ts)
        assert f"sign={expected_sign}" in url
        assert f"timestamp={ts}" in url

    def test_base_url_without_query_uses_question_mark(self) -> None:
        url = sign_dingtalk_url("https://x.example/path", "s", 1)
        assert "?timestamp=" in url

    def test_base_url_with_query_uses_amp(self) -> None:
        url = sign_dingtalk_url("https://x.example/path?a=1", "s", 1)
        assert "&timestamp=" in url


class TestFormatMarkdown:
    def test_includes_severity_badge(self) -> None:
        _, text = format_markdown(_notif(Severity.EMERGENCY))
        assert "🔴" in text
        assert "[EMERGENCY]" in text

    def test_includes_dock_phase(self) -> None:
        _, text = format_markdown(_notif())
        assert "DOCK1" in text
        assert "CRUISE" in text

    def test_includes_suggested_action(self) -> None:
        _, text = format_markdown(_notif())
        assert "notify" in text
        assert "本系统不下发指令" in text


def _make_robot(**kwargs) -> DingTalkRobot:
    base = {
        "id": "ops-primary",
        "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=X",
        "secret": "SEC",
        "min_severity": "RETURN",
    }
    base.update(kwargs)
    return DingTalkRobot.model_validate(base)


class TestDingTalkChannelSend:
    async def test_success(self) -> None:
        captured: dict = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = request.read()
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        channel = DingTalkChannel([_make_robot()], http=client, clock=lambda: 1700000000000)

        result = await channel.send(_notif(Severity.RETURN))
        await channel.close()
        await client.aclose()

        assert result.sent is True
        assert "timestamp=1700000000000" in captured["url"]
        import json as _json
        body = _json.loads(captured["body"])
        assert body["msgtype"] == "markdown"
        assert "TEST" in body["markdown"]["text"]

    async def test_skip_below_min_severity(self) -> None:
        called = False

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        channel = DingTalkChannel(
            [_make_robot(min_severity="RETURN")],
            http=client, clock=lambda: 1,
        )
        result = await channel.send(_notif(Severity.WARN))
        await channel.close()
        await client.aclose()

        assert result.sent is False
        assert result.detail["reason"] == "no_matching_robot"
        assert called is False

    async def test_dingtalk_errcode_nonzero_treated_as_failure(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"errcode": 310000, "errmsg": "keyword not in content"})

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        channel = DingTalkChannel([_make_robot()], http=client, clock=lambda: 1)

        result = await channel.send(_notif(Severity.BLOCK))
        await channel.close()
        await client.aclose()

        assert result.sent is False

    async def test_emergency_at_all(self) -> None:
        captured: dict = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            import json as _json
            captured["body"] = _json.loads(request.read())
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        channel = DingTalkChannel([_make_robot(min_severity="WARN")], http=client, clock=lambda: 1)

        await channel.send(_notif(Severity.EMERGENCY))
        await channel.close()
        await client.aclose()

        assert captured["body"]["at"]["isAtAll"] is True

    async def test_code_filter_exclude(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        channel = DingTalkChannel(
            [_make_robot(code_filter={"include": ["*"], "exclude": ["NOISY"]})],
            http=client, clock=lambda: 1,
        )
        result = await channel.send(_notif(code="NOISY"))
        await channel.close()
        await client.aclose()

        assert result.sent is False
