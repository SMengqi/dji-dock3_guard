"""collector 原频 flight_samples (OSD 每帧一采). 合成录制, 不依赖 sim."""

from __future__ import annotations

import json
import pathlib
import textwrap

import pytest

from dock_guard.analytics import collect
from dock_guard.analytics.models import FlightSample


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


def _make_recording(tmp_path: pathlib.Path, n_osd: int = 20) -> pathlib.Path:
    """n_osd 帧 drone OSD (含 attitude / position_state) + 对应 dock OSD (含 drc_state)."""
    rec = tmp_path / "rec"
    rec.mkdir()
    (rec / "topics").mkdir()
    base = 1700000000000
    frames = [{
        "recv_ts_ms": base, "dji_ts_ms": base, "direction": "up",
        "topic": "sys/product/TEST_DOCK_01/status", "payload": {"sub_type": 0},
    }]
    for t in range(n_osd):
        ts = base + t * 2000  # OSD ~0.5Hz
        frames.append({
            "recv_ts_ms": ts + 100, "dji_ts_ms": ts + 100, "direction": "up",
            "topic": "thing/product/TEST_DOCK_01/osd",
            "payload": {"data": {
                "wind_speed": 40, "drc_state": "connected",
                "sub_device": {"device_sn": "TEST_DRONE_01"},
            }, "timestamp": ts + 100},
        })
        frames.append({
            "recv_ts_ms": ts + 200, "dji_ts_ms": ts + 200, "direction": "up",
            "topic": "thing/product/TEST_DRONE_01/osd",
            "payload": {"data": {
                "mode_code": 5, "height": 30.0 + t,
                "vertical_speed": 0.5, "horizontal_speed": 3.0,
                "attitude_pitch": 1.0 + t, "attitude_roll": -2.0,
                "attitude_head": 90.0,
                "battery": {"capacity_percent": 100 - t},
                "position_state": {"is_fixed": 1, "gps_number": 14, "rtk_number": 22},
            }, "timestamp": ts + 200},
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


def test_flight_samples_one_per_osd_frame(tmp_path: pathlib.Path) -> None:
    cfg = _seed_config(tmp_path)
    rep = collect(_make_recording(tmp_path, 20), cfg)
    # 每个 drone OSD 帧一条 (±4 容差, 首帧 drone_sn 未知等边界)
    assert 16 <= len(rep.flight_samples) <= 20


def test_flight_sample_fields(tmp_path: pathlib.Path) -> None:
    cfg = _seed_config(tmp_path)
    rep = collect(_make_recording(tmp_path, 20), cfg)
    assert rep.flight_samples, "应有采样"
    s = rep.flight_samples[-1]
    assert isinstance(s, FlightSample)
    assert s.rel_ms >= 0
    assert s.attitude_pitch is not None
    assert s.attitude_head == 90.0
    assert s.horizontal_speed_ms == 3.0
    assert s.is_fixed in (True, False)      # position_state.is_fixed -> rtk_fixed
    assert s.drc_state == "connected"       # dock OSD 字段, latest facts 里可见


def test_flight_samples_monotonic(tmp_path: pathlib.Path) -> None:
    cfg = _seed_config(tmp_path)
    rep = collect(_make_recording(tmp_path, 15), cfg)
    ts = [s.rel_ms for s in rep.flight_samples]
    assert ts == sorted(ts)


def test_flight_samples_have_gps_rtk(tmp_path: pathlib.Path) -> None:
    cfg = _seed_config(tmp_path)
    rep = collect(_make_recording(tmp_path, 20), cfg)
    last = rep.flight_samples[-1]
    assert last.gps_number == 14
    assert last.rtk_number == 22
