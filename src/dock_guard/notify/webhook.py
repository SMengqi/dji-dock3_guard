"""通用 Webhook 通道 (设计 §7.5)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from typing import Any

import httpx

from dock_guard.notify.channel import ChannelResult
from dock_guard.notify.loader import WebhookEndpoint
from dock_guard.notify.notification import Notification
from dock_guard.types import Severity

DEFAULT_TIMEOUT_S = 5.0


def hmac_signature(secret: str, body: bytes) -> str:
    """HMAC-SHA256(secret, body) hex digest (设计 §7.5)."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


class DeadLetter:
    """简单内存 dead-letter. Phase 9 接 RotatingJsonlSink."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def append(self, endpoint_id: str, notif: Notification, reason: str) -> None:
        self.records.append({
            "endpoint_id": endpoint_id,
            "notif_id": notif.id,
            "notif_code": notif.code,
            "ts_ms": notif.ts_ms,
            "reason": reason,
        })


class WebhookChannel:
    def __init__(
        self,
        endpoints: list[WebhookEndpoint],
        *,
        http: httpx.AsyncClient | None = None,
        dead_letter: DeadLetter | None = None,
    ) -> None:
        self.endpoints = endpoints
        self._http = http or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_S)
        self._owns_http = http is None
        self.dead_letter = dead_letter or DeadLetter()

    @property
    def name(self) -> str:
        return "webhook"

    async def send(self, notif: Notification) -> ChannelResult:
        targets = [e for e in self.endpoints if self._should_send(e, notif)]
        if not targets:
            return ChannelResult(sent=False, detail={"reason": "no_matching_endpoint"})

        successes: list[str] = []
        failures: list[dict[str, Any]] = []
        dead_lettered: list[str] = []

        for ep in targets:
            ok, outcome = await self._send_with_retry(ep, notif)
            if ok:
                successes.append(ep.id)
            else:
                failures.append({"endpoint": ep.id, **outcome})
                self.dead_letter.append(ep.id, notif, reason=outcome.get("reason", "unknown"))
                dead_lettered.append(ep.id)

        return ChannelResult(
            sent=bool(successes),
            detail={
                "endpoints_sent": successes,
                **({"failures": failures} if failures else {}),
                **({"dead_lettered": dead_lettered} if dead_lettered else {}),
            },
        )

    def _should_send(self, ep: WebhookEndpoint, notif: Notification) -> bool:
        min_sev = Severity[ep.min_severity]
        if notif.severity < min_sev:
            return False
        cf = ep.code_filter
        if cf.exclude and notif.code in cf.exclude:
            return False
        if cf.include and "*" not in cf.include and notif.code not in cf.include:
            return False
        return True

    async def _send_with_retry(
        self, ep: WebhookEndpoint, notif: Notification
    ) -> tuple[bool, dict[str, Any]]:
        body_bytes = json.dumps(notif.to_dict(), ensure_ascii=False).encode("utf-8")
        sig = hmac_signature(ep.secret, body_bytes)
        headers = {
            "Content-Type": "application/json",
            "X-DockGuard-Signature": f"sha256={sig}",
            "X-DockGuard-Notification-Id": notif.id,
            "X-DockGuard-Ts": str(notif.ts_ms),
        }

        last_outcome: dict[str, Any] = {}
        max_attempts = ep.retry.max_attempts
        backoff = list(ep.retry.backoff_ms)

        for attempt in range(1, max_attempts + 1):
            try:
                resp = await self._http.post(
                    ep.url, content=body_bytes, headers=headers,
                    timeout=ep.timeout_ms / 1000.0,
                )
                if 200 <= resp.status_code < 300:
                    return True, {"http_status": resp.status_code, "attempt": attempt}
                last_outcome = {
                    "http_status": resp.status_code,
                    "attempt": attempt,
                    "reason": f"http_{resp.status_code}",
                }
            except httpx.HTTPError as e:
                last_outcome = {
                    "error": type(e).__name__,
                    "attempt": attempt,
                    "reason": "http_exception",
                }

            if attempt < max_attempts and attempt - 1 < len(backoff):
                await asyncio.sleep(backoff[attempt - 1] / 1000.0)

        last_outcome.setdefault("reason", "max_retries_exceeded")
        return False, last_outcome

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()
