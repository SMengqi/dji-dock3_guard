"""Stage 2 B4: /admin/* 控制端点 (设计 §8 + §10.5).

端点:
  POST /admin/mute/{dock_sn}    设置 / 解除 per-dock 静默
  POST /admin/global_mute       设置 / 解除全局静默
  GET  /admin/mutes             读当前静默状态
  POST /admin/reload-rules      重读 config/rules.yaml 替换 RuleEngine.rules

所有端点走 admin token (在 app.py 的 protected router 上挂 dep).

设计口径:
- 静默仅影响通道投递 (mute 门), 不影响 verdict 评估与 alerts.jsonl 落盘审计 (§6.5).
- 全局 mute 优先于 per-dock; 全局 mute 的 min_severity_to_send 默认 BLOCK
  (确保 EMERGENCY 永远透), per-dock 默认 EMERGENCY (即整个 dock 全静).
- reload 仅替换 RuleEngine.rules; dwell_state 保留 (rule_id 是稳定 key,
  消失的 rule_id 留个孤儿 dwell entry 也无害).
- reload 失败时 (yaml 校验错) 不替换现有 rules, 返回 400 + 错误详情.
"""

from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from dock_guard.coordinator.mute import MuteEntry
from dock_guard.http.state import HttpState
from dock_guard.rules.loader import load_rules_yaml
from dock_guard.types import Severity

SeverityName = Literal["EMERGENCY", "BLOCK", "RETURN", "WARN", "INFO"]


class DockMuteRequest(BaseModel):
    enabled: bool
    min_severity_to_send: SeverityName = "EMERGENCY"
    reason: str = ""
    duration_s: int = Field(default=0, ge=0)   # 0 = 永久


class GlobalMuteRequest(BaseModel):
    enabled: bool
    min_severity_to_send: SeverityName = "BLOCK"
    reason: str = ""


def _mute_to_dict(entry: MuteEntry | None) -> dict | None:
    if entry is None:
        return None
    return {
        "enabled": entry.enabled,
        "min_severity_to_send": entry.min_severity_to_send.name,
        "reason": entry.reason,
        "expires_at_ms": entry.expires_at_ms,
        "set_at_ms": entry.set_at_ms,
    }


def register_admin(router: APIRouter, state: HttpState) -> None:
    """注册 /admin/* 到 router. 调用方负责挂 admin token dep."""

    @router.post("/admin/mute/{dock_sn}")
    def set_dock_mute(dock_sn: str, body: DockMuteRequest) -> dict:
        coord = state.coordinator
        if coord is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AlertCoordinator 未挂载 (cfg.rules None?)",
            )
        now_ms = int(time.time() * 1000)
        entry = coord.mute.set_dock_mute(
            dock_sn,
            enabled=body.enabled,
            min_severity_to_send=Severity[body.min_severity_to_send],
            reason=body.reason,
            duration_s=body.duration_s,
            now_ms=now_ms,
        )
        return {"ok": True, "dock_sn": dock_sn, "mute": _mute_to_dict(entry)}

    @router.post("/admin/global_mute")
    def set_global_mute(body: GlobalMuteRequest) -> dict:
        coord = state.coordinator
        if coord is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AlertCoordinator 未挂载",
            )
        now_ms = int(time.time() * 1000)
        entry = coord.mute.set_global_mute(
            enabled=body.enabled,
            min_severity_to_send=Severity[body.min_severity_to_send],
            reason=body.reason,
            now_ms=now_ms,
        )
        return {"ok": True, "mute": _mute_to_dict(entry)}

    @router.get("/admin/mutes")
    def list_mutes() -> dict:
        coord = state.coordinator
        if coord is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AlertCoordinator 未挂载",
            )
        return {
            "global": _mute_to_dict(coord.mute.get_global_mute()),
            "docks": {
                sn: _mute_to_dict(entry)
                for sn, entry in coord.mute._dock_mutes.items()
            },
        }

    @router.post("/admin/reload-rules")
    def reload_rules() -> dict:
        engine = state.engine
        config_dir = state.config_dir
        if engine is None or config_dir is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="RuleEngine 或 config_dir 未挂载",
            )
        rules_path = config_dir / "rules.yaml"
        try:
            new_rules = load_rules_yaml(rules_path)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"reload failed: {type(e).__name__}: {e}",
            ) from e
        old_count = sum(1 for _ in engine.rules.all_rules())
        new_count = sum(1 for _ in new_rules.all_rules())
        engine.rules = new_rules
        return {
            "ok": True,
            "rules_path": str(rules_path),
            "old_rule_count": old_count,
            "new_rule_count": new_count,
        }
