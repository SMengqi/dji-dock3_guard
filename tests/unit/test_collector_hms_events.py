"""collector 采 hms_events (events method=hms). 合成录制."""

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


def _make_recording(tmp_path: pathlib.Path, hms_frames: list[dict]) -> pathlib.Path:
    """status 帧 + 若干 events hms 帧.
    hms_frames: [{"dt_ms":.., "dev":"drone"|"dock", "list":[{"code":..,"level":..,"module":..}, ...]}, ...]"""
    rec = tmp_path / "rec"
    rec.mkdir()
    (rec / "topics").mkdir()
    base = 1700000000000
    frames = [{
        "recv_ts_ms": base, "dji_ts_ms": base, "direction": "up",
        "topic": "sys/product/TEST_DOCK_01/status", "payload": {"sub_type": 0},
    }]
    for hf in hms_frames:
        ts = base + hf["dt_ms"]
        sn = "TEST_DRONE_01" if hf["dev"] == "drone" else "TEST_DOCK_01"
        frames.append({
            "recv_ts_ms": ts, "dji_ts_ms": ts, "direction": "up",
            "topic": f"thing/product/{sn}/events",
            "payload": {"method": "hms", "data": {"list": hf["list"]}, "tid": "t", "bid": "b"},
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


def test_hms_drone_event(tmp_path: pathlib.Path) -> None:
    rec = _make_recording(tmp_path, [
        {"dt_ms": 1000, "dev": "drone", "list": [{"code": "0x1B030019", "level": 0, "module": 3}]},
    ])
    rep = collect(rec, _seed_config(tmp_path))
    assert len(rep.hms_events) == 1
    e = rep.hms_events[0]
    assert e["code"] == "0x1B030019"
    assert e["level"] == 0 and e["module"] == 3
    assert e["device"] == "drone" and e["rel_ms"] == 1000


def test_hms_dock_event_device(tmp_path: pathlib.Path) -> None:
    rec = _make_recording(tmp_path, [
        {"dt_ms": 2000, "dev": "dock", "list": [{"code": "0x16100083", "level": 2, "module": 3}]},
    ])
    rep = collect(rec, _seed_config(tmp_path))
    assert len(rep.hms_events) == 1
    assert rep.hms_events[0]["device"] == "dock"
    assert rep.hms_events[0]["level"] == 2


def test_hms_multi_items_one_frame(tmp_path: pathlib.Path) -> None:
    rec = _make_recording(tmp_path, [
        {"dt_ms": 1000, "dev": "drone", "list": [
            {"code": "0xA", "level": 0, "module": 3},
            {"code": "0xB", "level": 1, "module": 0},
        ]},
    ])
    rep = collect(rec, _seed_config(tmp_path))
    assert len(rep.hms_events) == 2
    assert {e["code"] for e in rep.hms_events} == {"0xA", "0xB"}


def test_hms_empty_list_no_event(tmp_path: pathlib.Path) -> None:
    rec = _make_recording(tmp_path, [{"dt_ms": 1000, "dev": "drone", "list": []}])
    rep = collect(rec, _seed_config(tmp_path))
    assert rep.hms_events == []


def test_hms_missing_fields_default(tmp_path: pathlib.Path) -> None:
    rec = _make_recording(tmp_path, [{"dt_ms": 1000, "dev": "drone", "list": [{"code": "0xC"}]}])
    rep = collect(rec, _seed_config(tmp_path))
    assert len(rep.hms_events) == 1
    assert rep.hms_events[0]["code"] == "0xC"
    assert rep.hms_events[0]["level"] == -1 and rep.hms_events[0]["module"] == -1
