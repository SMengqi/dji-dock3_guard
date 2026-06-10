"""Stage 2 FastAPI app factory."""

from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI

from dock_guard.http.auth import make_admin_token_dependency
from dock_guard.http.events import register_events
from dock_guard.http.health import register_health
from dock_guard.http.state import HttpState


def build_app(state: HttpState) -> FastAPI:
    app = FastAPI(
        title="dock_guard control plane",
        version="2.0",
        docs_url="/docs",
    )
    # /healthz + /readyz 公共, 不挂 token dependency.
    public = APIRouter()
    register_health(public, state)
    app.include_router(public)

    # /events SSE 走 admin token (避免任意人监听运营事件流, §10.5);
    # B4 /admin/* 走同一个 dep, 重用减少漏挂可能.
    protected = APIRouter(
        dependencies=[Depends(make_admin_token_dependency(state))],
    )
    register_events(protected, state)
    app.include_router(protected)
    return app
