"""Phase 6 单元测试: Webhook 签名 + 重试 + dead letter (设计 §7.5)."""

from __future__ import annotations

import hashlib
import hmac
import json
from types import MappingProxyType

import httpx

from dock_guard.notify.loader import WebhookEndpoint
from dock_guard.notify.notification import Notification
from dock_guard.notify.webhook import DeadLetter, WebhookChannel, hmac_signature
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
    )


def _make_ep(**kwargs) -> WebhookEndpoint:
    base = {
        "id": "ops-platform",
        "url": "https://ops.example.com/dji/alarms",
        "secret": "SEC",
        "min_severity": "RETURN",
        "timeout_ms": 5000,
        "retry": {"max_attempts": 3, "backoff_ms": [0, 0, 0]},
    }
    base.update(kwargs)
    return WebhookEndpoint.model_validate(base)


class TestHmacSignature:
    def test_deterministic(self) -> None:
        sig1 = hmac_signature("secret", b'{"a":1}')
        sig2 = hmac_signature("secret", b'{"a":1}')
        assert sig1 == sig2

    def test_matches_manual_hmac(self) -> None:
        secret = "TESTSECRET"
        body = b'{"hello":"world"}'
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert hmac_signature(secret, body) == expected


class TestWebhookChannelSend:
    async def test_success_2xx(self) -> None:
        captured: dict = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(request.headers)
            captured["body"] = request.read()
            return httpx.Response(204)

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        channel = WebhookChannel([_make_ep()], http=client)

        result = await channel.send(_notif())
        await channel.close()
        await client.aclose()

        assert result.sent is True
        assert "x-dockguard-signature" in captured["headers"]
        body = json.loads(captured["body"])
        assert body["code"] == "TEST"

    async def test_skip_below_min_severity(self) -> None:
        called = False

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(200)

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        channel = WebhookChannel([_make_ep(min_severity="BLOCK")], http=client)

        result = await channel.send(_notif(Severity.WARN))
        await channel.close()
        await client.aclose()

        assert result.sent is False
        assert called is False

    async def test_retry_on_5xx_then_dead_letter(self) -> None:
        call_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(500)

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        dl = DeadLetter()
        channel = WebhookChannel([_make_ep()], http=client, dead_letter=dl)

        result = await channel.send(_notif())
        await channel.close()
        await client.aclose()

        assert call_count == 3   # max_attempts
        assert result.sent is False
        assert len(dl.records) == 1
        assert dl.records[0]["endpoint_id"] == "ops-platform"

    async def test_signature_in_header(self) -> None:
        captured: dict = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured["sig"] = request.headers.get("x-dockguard-signature")
            captured["body"] = request.read()
            return httpx.Response(200)

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        channel = WebhookChannel([_make_ep(secret="SEC")], http=client)

        await channel.send(_notif())
        await channel.close()
        await client.aclose()

        assert captured["sig"].startswith("sha256=")
        sig_hex = captured["sig"].removeprefix("sha256=")
        expected = hmac_signature("SEC", captured["body"])
        assert sig_hex == expected

    async def test_code_filter_exclude(self) -> None:
        called = False

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(200)

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        channel = WebhookChannel(
            [_make_ep(code_filter={"include": ["*"], "exclude": ["NOISY"]})],
            http=client,
        )

        result = await channel.send(_notif(code="NOISY"))
        await channel.close()
        await client.aclose()

        assert result.sent is False
        assert called is False
