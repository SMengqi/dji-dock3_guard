"""Stage 2 FastAPI app factory."""

from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI

from dock_guard.http.admin import register_admin
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

    # /events SSE + /admin/* 走同一个 admin token dep (§10.5).
    protected = APIRouter(
        dependencies=[Depends(make_admin_token_dependency(state))],
    )
    register_events(protected, state)
    register_admin(protected, state)
    app.include_router(protected)
    return app
