"""collector 采 transfer_events (services fly_to_point/takeoff_to_point). 合成录制."""

from __future__ import annotations

import json
import pathlib
import textwrap

import pytest

from dock_guard.analytics import collect


def _seed_config(tmp_path: pathlib.Path) -> pathlib.Path:
    repo = pathlib.Path(__file__).resolve().parents[2] / "config"
    if not (repo / "mode_code_map.yaml").exists():
        pytest.skip("repo config not present")
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    for name in ("mode_code_map.yaml", "alert_levels.yaml", "enums.yaml", "rules.yaml"):
        (cfg / name).symlink_to(repo / name)
    (cfg / "runtime.yaml").write_text(textwrap.dedent("""
        schema_version: 1
        mqtt:
          broker_url:  tcp://test:1883
          username:    "x"
          password:    "x"
        subscriptions:
          - dock_sn: TEST_DOCK_01
            enabled: true
    """))
    return cfg


def _make_recording(tmp_path: pathlib.Path, cmds: list[dict]) -> pathlib.Path:
    """status 帧 + 若干 services 命令帧.
    cmds: [{"dt_ms":.., "method":"fly_to_point", "height":71.5}, {"method":"takeoff_to_point","target_height":90.0}, {"method":"fly_to_point","no_points":True}, ...]"""
    rec = tmp_path / "rec"
    rec.mkdir()
    (rec / "topics").mkdir()
    base = 1700000000000
    frames = [{
        "recv_ts_ms": base, "dji_ts_ms": base, "direction": "up",
        "topic": "sys/product/TEST_DOCK_01/status", "payload": {"sub_type": 0},
    }]
    for cmd in cmds:
        ts = base + cmd["dt_ms"]
        m = cmd["method"]
        if m == "fly_to_point":
            if cmd.get("no_points"):
                data = {"max_speed": 5}
            else:
                data = {"points": [{"longitude": 1.0, "latitude": 2.0, "height": cmd["height"]}], "max_speed": 5}
        else:  # takeoff_to_point
            data = {"target_height": cmd["target_height"], "security_takeoff_height": 50.0}
        frames.append({
            "recv_ts_ms": ts, "dji_ts_ms": ts, "direction": "up",
            "topic": "thing/product/TEST_DOCK_01/services",
            "payload": {"method": m, "data": data, "tid": "t", "bid": "b"},
        })
    with (rec / "topics" / "x.jsonl").open("w", encoding="utf-8") as f:
        for fr in frames:
            f.write(json.dumps(fr) + "\n")
    (rec / "manifest.json").write_text(json.dumps({
        "schema_version": 1, "dock_sn": "TEST_DOCK_01", "drone_sn": "TEST_DRONE_01",
        "started_at_recv_ms": frames[0]["recv_ts_ms"],
        "ended_at_recv_ms": frames[-1]["recv_ts_ms"],
        "topics": [{
            "topic": "synthetic", "device_sn": "TEST_DOCK_01", "direction": "up",
            "count": len(frames),
            "first_recv_ts_ms": frames[0]["recv_ts_ms"],
            "last_recv_ts_ms": frames[-1]["recv_ts_ms"],
            "files": [{"name": "topics/x.jsonl", "count": len(frames),
                       "first_ms": frames[0]["recv_ts_ms"],
                       "last_ms": frames[-1]["recv_ts_ms"]}],
        }],
    }), encoding="utf-8")
    return rec


def test_fly_to_point_event(tmp_path: pathlib.Path) -> None:
    rec = _make_recording(tmp_path, [{"dt_ms": 1000, "method": "fly_to_point", "height": 71.5}])
    rep = collect(rec, _seed_config(tmp_path))
    assert len(rep.transfer_events) == 1
    e = rep.transfer_events[0]
    assert e["type"] == "fly_to"
    assert e["target_height"] == 71.5
    assert e["rel_ms"] == 1000


def test_takeoff_to_point_event(tmp_path: pathlib.Path) -> None:
    rec = _make_recording(tmp_path, [{"dt_ms": 2000, "method": "takeoff_to_point", "target_height": 90.0}])
    rep = collect(rec, _seed_config(tmp_path))
    assert len(rep.transfer_events) == 1
    assert rep.transfer_events[0]["type"] == "takeoff"
    assert rep.transfer_events[0]["target_height"] == 90.0


def test_fly_to_missing_points_height_none(tmp_path: pathlib.Path) -> None:
    rec = _make_recording(tmp_path, [{"dt_ms": 1000, "method": "fly_to_point", "no_points": True}])
    rep = collect(rec, _seed_config(tmp_path))
    assert len(rep.transfer_events) == 1
    assert rep.transfer_events[0]["type"] == "fly_to"
    assert rep.transfer_events[0]["target_height"] is None


def test_no_transfer_commands_empty(tmp_path: pathlib.Path) -> None:
    rec = _make_recording(tmp_path, [])
    rep = collect(rec, _seed_config(tmp_path))
    assert rep.transfer_events == []
