"""Stage 2 B1: /healthz + /readyz 单测 (设计 §9.3)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from dock_guard.http.app import build_app
from dock_guard.http.state import HttpState


def _make_client(state: HttpState) -> TestClient:
    return TestClient(build_app(state))


class TestHealthz:
    def test_always_200(self) -> None:
        state = HttpState(admin_token="t")
        client = _make_client(state)
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "service": "dock_guard"}

    def test_no_token_required(self) -> None:
        """K8s liveness 不应需 token."""
        state = HttpState(admin_token="t")
        client = _make_client(state)
        assert client.get("/healthz").status_code == 200


class TestReadyz:
    def test_503_when_mqtt_disconnected(self) -> None:
        state = HttpState(admin_token="t", mqtt_connected=False, seen_first_osd=False)
        client = _make_client(state)
        resp = client.get("/readyz")
        assert resp.status_code == 503
        body = resp.json()
        assert body["ok"] is False
        assert "mqtt_not_connected" in body["reasons"]
        assert "no_osd_received" in body["reasons"]

    def test_503_when_mqtt_ok_but_no_osd(self) -> None:
        state = HttpState(admin_token="t", mqtt_connected=True, seen_first_osd=False)
        client = _make_client(state)
        resp = client.get("/readyz")
        assert resp.status_code == 503
        assert resp.json()["reasons"] == ["no_osd_received"]

    def test_200_when_mqtt_and_osd_ok(self) -> None:
        state = HttpState(admin_token="t", mqtt_connected=True, seen_first_osd=True)
        client = _make_client(state)
        resp = client.get("/readyz")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_replay_mode_skips_mqtt_check(self) -> None:
        """--replay 模式没 broker, mqtt_connected 永远 False, 但 readyz 不应卡住."""
        state = HttpState(
            admin_token="t",
            mqtt_connected=False,
            seen_first_osd=True,
            replay_mode=True,
        )
        client = _make_client(state)
        resp = client.get("/readyz")
        assert resp.status_code == 200
