"""collector 采 hsi_samples (drc/up hsi_info_push). 合成录制, 不依赖真机."""

from __future__ import annotations

import json
import pathlib
import textwrap

import pytest

from dock_guard.analytics import collect
from dock_guard.analytics.models import HsiSample


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


def _make_recording(tmp_path: pathlib.Path, n: int = 15) -> pathlib.Path:
    """n 帧: drone OSD(含 elevation) + drc/up hsi_info_push(下视距离)."""
    rec = tmp_path / "rec"
    rec.mkdir()
    (rec / "topics").mkdir()
    base = 1700000000000
    frames = [{
        "recv_ts_ms": base, "dji_ts_ms": base, "direction": "up",
        "topic": "sys/product/TEST_DOCK_01/status", "payload": {"sub_type": 0},
    }]
    for t in range(n):
        ts = base + t * 1000
        frames.append({
            "recv_ts_ms": ts + 100, "dji_ts_ms": ts + 100, "direction": "up",
            "topic": "thing/product/TEST_DRONE_01/osd",
            "payload": {"data": {
                "mode_code": 5, "height": 40.0 + t, "elevation": 2.0 + t,
                "battery": {"capacity_percent": 100 - t},
            }, "timestamp": ts + 100},
        })
        frames.append({
            "recv_ts_ms": ts + 150, "dji_ts_ms": ts + 150, "direction": "up",
            "topic": "thing/product/TEST_DOCK_01/osd",
            "payload": {"data": {
                "wind_speed": 30,
                "sub_device": {"device_sn": "TEST_DRONE_01"},
            }, "timestamp": ts + 150},
        })
        dd = 60000 if t < 3 else 1500 + t * 100
        frames.append({
            "recv_ts_ms": ts + 200, "dji_ts_ms": ts + 200, "direction": "up",
            "topic": "thing/product/TEST_DOCK_01/drc/up",
            "payload": {"method": "hsi_info_push", "data": {
                "down_distance": dd, "down_enable": True, "down_work": t >= 3,
                "up_distance": 60000, "up_enable": False, "up_work": True,
                "around_distances": [3000 + t, 4000 + t],
            }},
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


def test_hsi_samples_one_per_push(tmp_path: pathlib.Path) -> None:
    rep = collect(_make_recording(tmp_path, 15), _seed_config(tmp_path))
    assert 12 <= len(rep.hsi_samples) <= 15


def test_hsi_sample_fields_and_elevation(tmp_path: pathlib.Path) -> None:
    rep = collect(_make_recording(tmp_path, 15), _seed_config(tmp_path))
    assert rep.hsi_samples, "应有 hsi 采样"
    s = rep.hsi_samples[-1]
    assert isinstance(s, HsiSample)
    assert s.down_distance_mm == 1500 + 14 * 100
    assert s.down_work is True
    assert s.up_enable is False
    assert s.around_distances_mm == [3000 + 14, 4000 + 14]
    assert s.elevation_m is not None


def test_hsi_keeps_invalid_sentinel(tmp_path: pathlib.Path) -> None:
    rep = collect(_make_recording(tmp_path, 15), _seed_config(tmp_path))
    assert any(s.down_distance_mm == 60000 for s in rep.hsi_samples)
