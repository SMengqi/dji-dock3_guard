"""Stage 2 B1+B2: ADMIN_TOKEN 鉴权单测."""

from __future__ import annotations

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from dock_guard.http.auth import (
    TokenMissing,
    load_admin_token,
    make_admin_token_dependency,
)
from dock_guard.http.state import HttpState


class TestLoadAdminToken:
    def test_none_raises(self) -> None:
        with pytest.raises(TokenMissing, match="ADMIN_TOKEN 未注入"):
            load_admin_token(None)

    def test_empty_string_raises(self) -> None:
        with pytest.raises(TokenMissing):
            load_admin_token("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(TokenMissing):
            load_admin_token("   ")

    def test_valid_returns_stripped(self) -> None:
        assert load_admin_token("  secret123  ") == "secret123"


def _make_protected_app(token: str = "supersecret") -> FastAPI:
    """构造一个最小 app, 挂一个 /protected 路由用 token dependency."""
    state = HttpState(admin_token=token)
    app = FastAPI()
    router = APIRouter(dependencies=[Depends(make_admin_token_dependency(state))])

    @router.get("/protected")
    def protected() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(router)
    return app


class TestAdminTokenDependency:
    def test_no_header_401(self) -> None:
        client = TestClient(_make_protected_app())
        resp = client.get("/protected")
        assert resp.status_code == 401
        assert "missing or invalid admin token" in resp.json()["detail"]

    def test_wrong_bearer_401(self) -> None:
        client = TestClient(_make_protected_app(token="right"))
        resp = client.get("/protected", headers={"Authorization": "Bearer wrong"})
        assert resp.status_code == 401

    def test_correct_bearer_200(self) -> None:
        client = TestClient(_make_protected_app(token="right"))
        resp = client.get("/protected", headers={"Authorization": "Bearer right"})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_correct_x_admin_token_header_200(self) -> None:
        client = TestClient(_make_protected_app(token="right"))
        resp = client.get("/protected", headers={"X-Admin-Token": "right"})
        assert resp.status_code == 200

    def test_bearer_case_insensitive(self) -> None:
        client = TestClient(_make_protected_app(token="right"))
        resp = client.get("/protected", headers={"Authorization": "bearer right"})
        assert resp.status_code == 200

    def test_bearer_preferred_over_x_admin_token(self) -> None:
        """两个 header 同时存在时 Bearer 优先 (auth.py 的 if/elif 顺序)."""
        client = TestClient(_make_protected_app(token="right"))
        resp = client.get(
            "/protected",
            headers={"Authorization": "Bearer right", "X-Admin-Token": "wrong"},
        )
        assert resp.status_code == 200
