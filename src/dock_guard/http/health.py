"""Stage 2: /healthz + /readyz (设计 §9.3).

§9.3 文本:
  GET /healthz  -> 200 永远 (除非进程死了)
  GET /readyz   -> 200 iff:
    - MQTT 已连接 OR replay 模式
    - 所有 yaml 加载成功
    - warming_up 全部 false (启动 60s 后)
    - 至少一个 dock 收到过 OSD

B1 仅实现前两条 (mqtt + first OSD). warming_up + 多 dock 留 Stage 3+
(B 多机场上线时).
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from dock_guard.http.state import HttpState


def register_health(router: APIRouter, state: HttpState) -> None:
    @router.get("/healthz")
    def healthz() -> dict[str, object]:
        return {"ok": True, "service": "dock_guard"}

    @router.get("/readyz")
    def readyz(response: Response) -> dict[str, object]:
        reasons: list[str] = []
        if not state.replay_mode and not state.mqtt_connected:
            reasons.append("mqtt_not_connected")
        if not state.seen_first_osd:
            reasons.append("no_osd_received")
        if reasons:
            response.status_code = 503
            return {"ok": False, "reasons": reasons}
        return {"ok": True}
