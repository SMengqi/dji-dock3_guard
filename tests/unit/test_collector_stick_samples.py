"""collector 采 stick_samples (drc/down stick_control). 合成录制, 不依赖真机."""

from __future__ import annotations

import json
import pathlib
import textwrap

import pytest

from dock_guard.analytics import collect
from dock_guard.analytics.models import StickSample


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


def _make_recording(tmp_path: pathlib.Path, sticks: list[dict]) -> pathlib.Path:
    """status 帧 (设 first_ts=base) + 若干 drc/down stick_control 帧.

    sticks: [{"dt_ms": 1000, "roll": 1024, ...}, ...] dt_ms 为距 base 的偏移.
    """
    rec = tmp_path / "rec"
    rec.mkdir()
    (rec / "topics").mkdir()
    base = 1700000000000
    frames = [{
        "recv_ts_ms": base, "dji_ts_ms": base, "direction": "up",
        "topic": "sys/product/TEST_DOCK_01/status", "payload": {"sub_type": 0},
    }]
    for st in sticks:
        ts = base + st["dt_ms"]
        data = {k: st[k] for k in ("roll", "pitch", "yaw", "throttle") if k in st}
        frames.append({
            "recv_ts_ms": ts, "dji_ts_ms": ts, "direction": "down",
            "topic": "thing/product/TEST_DOCK_01/drc/down",
            "payload": {"method": "stick_control", "data": data, "seq": 1},
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


def test_collect_stick_samples_basic(tmp_path: pathlib.Path) -> None:
    rec = _make_recording(tmp_path, [
        {"dt_ms": 1000, "roll": 1024, "pitch": 1024, "yaw": 1024, "throttle": 1024},
        {"dt_ms": 2000, "roll": 1354, "pitch": 800, "yaw": 364, "throttle": 1684},
    ])
    rep = collect(rec, _seed_config(tmp_path))
    assert len(rep.stick_samples) == 2
    s0, s1 = rep.stick_samples
    assert isinstance(s0, StickSample)
    assert (s0.rel_ms, s0.roll) == (1000, 1024)
    assert (s1.rel_ms, s1.roll, s1.pitch, s1.yaw, s1.throttle) == (2000, 1354, 800, 364, 1684)


def test_collect_stick_missing_axis_none(tmp_path: pathlib.Path) -> None:
    rec = _make_recording(tmp_path, [{"dt_ms": 1000, "roll": 1354}])
    rep = collect(rec, _seed_config(tmp_path))
    assert len(rep.stick_samples) == 1
    s = rep.stick_samples[0]
    assert s.roll == 1354 and s.pitch is None and s.yaw is None and s.throttle is None


def test_collect_no_stick_empty(tmp_path: pathlib.Path) -> None:
    rec = _make_recording(tmp_path, [])
    rep = collect(rec, _seed_config(tmp_path))
    assert rep.stick_samples == []
