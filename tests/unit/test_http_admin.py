"""Stage 2 B4: /admin/* 端点单测."""

from __future__ import annotations

import pathlib
import textwrap

import pytest
from fastapi.testclient import TestClient

from dock_guard.aggregator import DockAggregator
from dock_guard.config import load_app_config
from dock_guard.coordinator import AlertCoordinator
from dock_guard.http.app import build_app
from dock_guard.http.state import HttpState
from dock_guard.rules import RuleEngine


_GOOD_ENV = {
    "MQTT_BROKER_URL": "tcp://test:1883",
    "MQTT_USERNAME": "u", "MQTT_PASSWORD": "p",
    "MQTT_DOCK_SN": "TEST_DOCK_01",
}


def _bootstrap(tmp_path: pathlib.Path) -> tuple[TestClient, HttpState]:
    """复用仓库 mode_code_map / alert_levels / enums / rules.yaml,
    合成最小 runtime.yaml; 构造完整的 cfg + coordinator + engine + http_state."""
    repo = pathlib.Path(__file__).resolve().parents[2] / "config"
    if not (repo / "mode_code_map.yaml").exists():
        pytest.skip("repo config not present")
    for name in ("mode_code_map.yaml", "alert_levels.yaml", "enums.yaml", "rules.yaml"):
        (tmp_path / name).symlink_to(repo / name)
    (tmp_path / "runtime.yaml").write_text(textwrap.dedent("""
        schema_version: 1
        mqtt:
          broker_url:  ${MQTT_BROKER_URL}
          username:    ${MQTT_USERNAME}
          password:    ${MQTT_PASSWORD}
        subscriptions:
          - dock_sn: ${MQTT_DOCK_SN}
            enabled: true
    """))

    cfg = load_app_config(tmp_path, env=_GOOD_ENV)
    agg = DockAggregator("TEST_DOCK_01", cfg)
    engine = RuleEngine(cfg.rules, agg)
    coordinator = AlertCoordinator(cfg)
    state = HttpState(
        admin_token="t",
        mqtt_connected=True,
        seen_first_osd=True,
        coordinator=coordinator,
        engine=engine,
        config_dir=tmp_path,
    )
    return TestClient(build_app(state)), state


HDR = {"Authorization": "Bearer t"}


# ─── /admin/mute/{dock_sn} ─────────────────────────────────────


class TestDockMute:
    def test_requires_token(self, tmp_path: pathlib.Path) -> None:
        client, _ = _bootstrap(tmp_path)
        resp = client.post("/admin/mute/X", json={"enabled": True})
        assert resp.status_code == 401

    def test_set_mute_enabled(self, tmp_path: pathlib.Path) -> None:
        client, state = _bootstrap(tmp_path)
        resp = client.post(
            "/admin/mute/DOCK_X",
            json={"enabled": True, "reason": "maintenance"},
            headers=HDR,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["dock_sn"] == "DOCK_X"
        assert body["mute"]["enabled"] is True
        assert body["mute"]["reason"] == "maintenance"
        assert body["mute"]["min_severity_to_send"] == "EMERGENCY"
        assert state.coordinator.mute.get_dock_mute("DOCK_X") is not None

    def test_set_mute_with_duration(self, tmp_path: pathlib.Path) -> None:
        client, _ = _bootstrap(tmp_path)
        resp = client.post(
            "/admin/mute/D1",
            json={"enabled": True, "duration_s": 60, "reason": "burn-in"},
            headers=HDR,
        )
        assert resp.status_code == 200
        m = resp.json()["mute"]
        assert m["expires_at_ms"] > m["set_at_ms"]
        assert m["expires_at_ms"] - m["set_at_ms"] == 60_000

    def test_invalid_severity_rejected(self, tmp_path: pathlib.Path) -> None:
        client, _ = _bootstrap(tmp_path)
        resp = client.post(
            "/admin/mute/D1",
            json={"enabled": True, "min_severity_to_send": "PANIC"},
            headers=HDR,
        )
        assert resp.status_code == 422


# ─── /admin/global_mute ─────────────────────────────────────────


class TestGlobalMute:
    def test_set_global_mute(self, tmp_path: pathlib.Path) -> None:
        client, state = _bootstrap(tmp_path)
        resp = client.post(
            "/admin/global_mute",
            json={"enabled": True, "reason": "off-hours"},
            headers=HDR,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["mute"]["enabled"] is True
        assert body["mute"]["min_severity_to_send"] == "BLOCK"
        assert state.coordinator.mute.get_global_mute() is not None


# ─── /admin/mutes ───────────────────────────────────────────────


class TestListMutes:
    def test_initial_empty(self, tmp_path: pathlib.Path) -> None:
        client, _ = _bootstrap(tmp_path)
        resp = client.get("/admin/mutes", headers=HDR)
        assert resp.status_code == 200
        body = resp.json()
        assert body["global"] is None
        assert body["docks"] == {}

    def test_after_set(self, tmp_path: pathlib.Path) -> None:
        client, _ = _bootstrap(tmp_path)
        client.post("/admin/mute/D1", json={"enabled": True}, headers=HDR)
        client.post("/admin/global_mute", json={"enabled": True}, headers=HDR)
        resp = client.get("/admin/mutes", headers=HDR)
        assert resp.status_code == 200
        body = resp.json()
        assert body["global"]["enabled"] is True
        assert "D1" in body["docks"]
        assert body["docks"]["D1"]["enabled"] is True


# ─── /admin/reload-rules ────────────────────────────────────────


class TestReloadRules:
    def test_reload_returns_counts(self, tmp_path: pathlib.Path) -> None:
        client, state = _bootstrap(tmp_path)
        original_count = sum(1 for _ in state.engine.rules.all_rules())
        resp = client.post("/admin/reload-rules", headers=HDR)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["old_rule_count"] == original_count
        assert body["new_rule_count"] == original_count

    def test_reload_picks_up_new_rules_yaml(self, tmp_path: pathlib.Path) -> None:
        client, state = _bootstrap(tmp_path)
        rules_yaml = tmp_path / "rules.yaml"
        rules_yaml.unlink()
        rules_yaml.write_text(textwrap.dedent("""
            version: 2
            defaults:
              cooldown_ms: 30000
              dwell_enter_ms: 0
              dwell_exit_ms: 0
            preflight_block:
              - id: preflight.emergency_stop_pressed
                desc: 急停
                phase: [PREFLIGHT]
                all:
                  - { fact: emergency_stop_pressed, op: "==", value: true }
                verdict:
                  level: block
                  code: PREFLIGHT_EMERGENCY_STOP_PRESSED
                  suggested_action: reject_takeoff
            inflight_escalate: []
            maintenance_advisory: []
        """))
        resp = client.post("/admin/reload-rules", headers=HDR)
        assert resp.status_code == 200
        body = resp.json()
        assert body["new_rule_count"] == 1
        assert sum(1 for _ in state.engine.rules.all_rules()) == 1

    def test_reload_bad_yaml_returns_400_and_keeps_old(
        self, tmp_path: pathlib.Path
    ) -> None:
        client, state = _bootstrap(tmp_path)
        before = sum(1 for _ in state.engine.rules.all_rules())
        rules_yaml = tmp_path / "rules.yaml"
        rules_yaml.unlink()
        rules_yaml.write_text("this: is: not: valid: yaml: ::")
        resp = client.post("/admin/reload-rules", headers=HDR)
        assert resp.status_code == 400
        assert "reload failed" in resp.json()["detail"]
        assert sum(1 for _ in state.engine.rules.all_rules()) == before
