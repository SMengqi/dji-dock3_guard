"""Stage 2 FastAPI app factory."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from dock_guard.http.health import register_health
from dock_guard.http.state import HttpState


def build_app(state: HttpState) -> FastAPI:
    app = FastAPI(
        title="dock_guard control plane",
        version="2.0",
        docs_url="/docs",   # B3/B4 还会挂 /events 与 /admin, 现在仅有 /healthz /readyz
    )
    # /healthz + /readyz 公共, 不挂 token dependency.
    public = APIRouter()
    register_health(public, state)
    app.include_router(public)
    # B3 /events SSE + B4 /admin/* 后续注册.
    return app
