"""钉钉机器人通道 (设计 §7.6)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import urllib.parse
from typing import Any

import httpx

from dock_guard.notify.channel import ChannelResult
from dock_guard.notify.loader import DingTalkRobot
from dock_guard.notify.notification import Notification
from dock_guard.types import Severity

SEVERITY_BADGE: dict[Severity, str] = {
    Severity.EMERGENCY: "🔴",
    Severity.BLOCK: "🟠",
    Severity.RETURN: "🟡",
    Severity.WARN: "🟢",
    Severity.INFO: "⚪",
}

DINGTALK_TIMEOUT_S = 5.0


def sign_dingtalk_url(base_url: str, secret: str, timestamp_ms: int) -> str:
    """钉钉自定义机器人加签算法 (设计 §7.6.2)."""
    string_to_sign = f"{timestamp_ms}\n{secret}"
    hmac_code = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    b64 = base64.b64encode(hmac_code).decode("utf-8")
    sign = urllib.parse.quote_plus(b64)
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}timestamp={timestamp_ms}&sign={sign}"


def format_markdown(notif: Notification) -> tuple[str, str]:
    """返回 (title, markdown_text). 设计 §7.6.3."""
    badge = SEVERITY_BADGE.get(notif.severity, "")
    title = f"[{notif.severity.name}] {notif.code} @{notif.context.get('dock_sn', '')}"

    ctx = notif.context
    lines = [
        f"**[{notif.severity.name}] {badge} {notif.code}**",
        "",
        f"机场: `{ctx.get('dock_sn', '?')}`  阶段: `{ctx.get('phase', '?')}`",
    ]
    if notif.verdict_payload:
        facts = notif.verdict_payload.get("facts", {})
        if facts:
            fact_lines = "; ".join(f"`{k}`=`{v}`" for k, v in list(facts.items())[:6])
            lines.append(f"facts: {fact_lines}")
    lines.append(
        f"建议动作: `{notif.suggested_action}` "
        "(本系统不下发指令, 请人工或下游系统处置)"
    )
    return title, "\n\n".join(lines)


class DingTalkChannel:
    def __init__(
        self,
        robots: list[DingTalkRobot],
        *,
        http: httpx.AsyncClient | None = None,
        clock: Any = None,
    ) -> None:
        self.robots = robots
        self._http = http or httpx.AsyncClient(timeout=DINGTALK_TIMEOUT_S)
        self._owns_http = http is None
        self._clock = clock or (lambda: int(time.time() * 1000))

    @property
    def name(self) -> str:
        return "dingtalk"

    async def send(self, notif: Notification) -> ChannelResult:
        targets = [r for r in self.robots if self._should_send(r, notif)]
        if not targets:
            return ChannelResult(sent=False, detail={"reason": "no_matching_robot"})

        successes: list[str] = []
        failures: list[dict[str, Any]] = []

        for robot in targets:
            ok, detail = await self._send_one(robot, notif)
            if ok:
                successes.append(robot.id)
            else:
                failures.append({"robot": robot.id, **detail})

        sent = bool(successes)
        return ChannelResult(
            sent=sent,
            detail=(
                {"robots_sent": successes, "failures": failures}
                if failures else {"robots_sent": successes}
            ),
        )

    def _should_send(self, robot: DingTalkRobot, notif: Notification) -> bool:
        min_sev = Severity[robot.min_severity]
        if notif.severity < min_sev:
            return False
        cf = robot.code_filter
        if cf.exclude and notif.code in cf.exclude:
            return False
        if cf.include and "*" not in cf.include and notif.code not in cf.include:
            return False
        return True

    async def _send_one(
        self, robot: DingTalkRobot, notif: Notification
    ) -> tuple[bool, dict[str, Any]]:
        title, text = format_markdown(notif)
        signed_url = sign_dingtalk_url(robot.webhook_url, robot.secret, self._clock())

        at_all = (
            robot.at_all_on_emergency
            and notif.severity == Severity.EMERGENCY
        )
        body = {
            "msgtype": "markdown",
            "markdown": {"title": title, "text": text},
            "at": {
                "atMobiles": (
                    list(robot.at_mobiles_on_emergency)
                    if notif.severity == Severity.EMERGENCY else []
                ),
                "isAtAll": at_all,
            },
        }
        try:
            resp = await self._http.post(signed_url, json=body)
        except httpx.HTTPError as e:
            return False, {"error": type(e).__name__, "message": str(e)}
        try:
            data = resp.json()
        except Exception:
            return False, {"http_status": resp.status_code, "body": resp.text[:200]}
        errcode = data.get("errcode")
        if errcode != 0:
            return False, {
                "http_status": resp.status_code,
                "errcode": errcode,
                "errmsg": data.get("errmsg"),
            }
        return True, {"http_status": resp.status_code, "errcode": 0}

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()
