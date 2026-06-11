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
from dock_guard.types import Phase, Severity

SEVERITY_BADGE: dict[Severity, str] = {
    Severity.EMERGENCY: "🔴",
    Severity.BLOCK: "🟠",
    Severity.RETURN: "🟡",
    Severity.WARN: "🟢",
    Severity.INFO: "⚪",
}

# 中文化字典 (让钉钉群里运维一眼看懂)
SEVERITY_CN: dict[Severity, str] = {
    Severity.EMERGENCY: "紧急",
    Severity.BLOCK: "拦阻",
    Severity.RETURN: "召回",
    Severity.WARN: "警告",
    Severity.INFO: "提示",
}

PHASE_CN: dict[Phase, str] = {
    Phase.IDLE: "待机",
    Phase.PREFLIGHT: "起飞前",
    Phase.TAKEOFF: "起飞中",
    Phase.CRUISE: "巡航中",
    Phase.AVOIDANCE: "避障中",
    Phase.RTH: "返航中",
    Phase.LANDING: "降落中",
    Phase.POSTFLIGHT: "落地后",
    Phase.OFFLINE: "离线",
    Phase.UPGRADING: "升级中",
}

ACTION_CN: dict[str, str] = {
    "reject_takeoff": "🛑 拒绝起飞",
    "return_home":    "🔙 立即返航",
    "notify":         "📋 仅记录, 无需处置",
    "investigate":    "🔍 现场检查处理",
}

# 钉钉端点 oapi.dingtalk.com 国内访问偶尔慢, 5s 偏紧;
# 10s 既能容忍 LAN 抖动, 又不至于让 graceful shutdown 卡太久.
# (broadxt 真实环境 2026-06-11 ConnectTimeout 后调整.)
DINGTALK_TIMEOUT_S = 10.0


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


def _phase_cn(phase_str: str) -> str:
    """phase 名 -> 中文; 无法解析时回原文."""
    try:
        return PHASE_CN.get(Phase(phase_str), phase_str)
    except ValueError:
        return phase_str


def format_markdown(notif: Notification) -> tuple[str, str]:
    """返回 (title, markdown_text). 设计 §7.6.3.

    人话化版本: 标题用规则中文 desc, 阶段 / 严重度 / 建议都译成中文,
    触发事实带上阈值, 末尾标 rule_id 便于排查.
    """
    badge = SEVERITY_BADGE.get(notif.severity, "")
    sev_cn = SEVERITY_CN.get(notif.severity, notif.severity.name)
    ctx = notif.context
    payload = notif.verdict_payload or {}
    desc = payload.get("desc") or ""
    rule_id = payload.get("rule_id") or "?"
    phase_raw = str(ctx.get("phase", "?"))
    phase_cn = _phase_cn(phase_raw)
    action_cn = ACTION_CN.get(notif.suggested_action, notif.suggested_action)

    # 标题: 钉钉摘要栏看到的就是这个
    headline = desc or notif.code   # 没 desc 退回 code 不丢信息
    title = f"[{sev_cn}] {headline} @{ctx.get('dock_sn', '')}"

    lines = [
        f"**{badge} [{sev_cn}] {headline}**",
        "",
        f"机场: `{ctx.get('dock_sn', '?')}`",
        f"阶段: {phase_cn}（`{phase_raw}`）",
    ]

    # 触发事实: 把对应阈值并排展示, 让运维一眼看到"为什么触发"
    facts = payload.get("facts", {})
    thresholds = payload.get("thresholds", {})
    if facts:
        fact_lines: list[str] = []
        for k, v in list(facts.items())[:6]:
            thr = thresholds.get(k)
            if thr:
                fact_lines.append(f"`{k}` = `{v}`（阈值 `{thr}`）")
            else:
                fact_lines.append(f"`{k}` = `{v}`")
        lines.append("触发事实: " + "; ".join(fact_lines))

    lines.append(f"建议: **{action_cn}**")
    lines.append("")
    lines.append(
        f"> 告警代码: `{notif.code}` · 规则: `{rule_id}`\n"
        "> 本系统不下发指令, 请人工或下游系统处置"
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
