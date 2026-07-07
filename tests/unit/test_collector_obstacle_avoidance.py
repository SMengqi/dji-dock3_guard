"""collector 从 drone OSD 采 FlightSample.oa_down/horizon/up. 合成录制."""

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


def _make_recording(tmp_path: pathlib.Path, osd_rows: list[dict]) -> pathlib.Path:
    """status 帧 + drone OSD 帧. osd_rows: [{"dt_ms":.., "oa":{"downside":1,...}|None}, ...]"""
    rec = tmp_path / "rec"
    rec.mkdir()
    (rec / "topics").mkdir()
    base = 1700000000000
    frames = [{
        "recv_ts_ms": base, "dji_ts_ms": base, "direction": "up",
        "topic": "sys/product/TEST_DOCK_01/status", "payload": {"sub_type": 0},
    }]
    for row in osd_rows:
        ts = base + row["dt_ms"]
        data = {"mode_code": 5, "height": 40.0}
        if row.get("oa") is not None:
            data["obstacle_avoidance"] = row["oa"]
        frames.append({
            "recv_ts_ms": ts, "dji_ts_ms": ts, "direction": "up",
            "topic": "thing/product/TEST_DRONE_01/osd",
            "payload": {"data": data, "timestamp": ts},
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


def test_oa_all_three(tmp_path: pathlib.Path) -> None:
    rec = _make_recording(tmp_path, [
        {"dt_ms": 1000, "oa": {"downside": 1, "horizon": 1, "upside": 0}},
    ])
    rep = collect(rec, _seed_config(tmp_path))
    withoa = [s for s in rep.flight_samples if s.oa_down is not None]
    assert len(withoa) == 1
    assert (withoa[0].oa_down, withoa[0].oa_horizon, withoa[0].oa_up) == (1, 1, 0)


def test_oa_missing_none(tmp_path: pathlib.Path) -> None:
    rec = _make_recording(tmp_path, [{"dt_ms": 1000, "oa": None}])  # 无 obstacle_avoidance
    rep = collect(rec, _seed_config(tmp_path))
    assert rep.flight_samples, "应有 flight_samples"
    assert all(s.oa_down is None and s.oa_horizon is None and s.oa_up is None
               for s in rep.flight_samples)


def test_oa_partial(tmp_path: pathlib.Path) -> None:
    rec = _make_recording(tmp_path, [{"dt_ms": 1000, "oa": {"downside": 1}}])  # 仅 downside
    rep = collect(rec, _seed_config(tmp_path))
    withoa = [s for s in rep.flight_samples if s.oa_down is not None]
    assert len(withoa) == 1
    assert withoa[0].oa_down == 1
    assert withoa[0].oa_horizon is None and withoa[0].oa_up is None
