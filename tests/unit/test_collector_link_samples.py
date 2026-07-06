"""collector 采 link_samples (drc/up drc_geo_connect_info_push). 合成录制."""

from __future__ import annotations

import json
import pathlib
import textwrap

import pytest

from dock_guard.analytics import collect
from dock_guard.analytics.models import LinkSample


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


def _make_recording(tmp_path: pathlib.Path, links: list[dict]) -> pathlib.Path:
    """status 帧 (设 first_ts=base) + 若干 drc/up drc_geo_connect_info_push 帧.
    links: [{"dt_ms":.., "sdr":.., "4g":.., "no_wl":bool}, ...]"""
    rec = tmp_path / "rec"
    rec.mkdir()
    (rec / "topics").mkdir()
    base = 1700000000000
    frames = [{
        "recv_ts_ms": base, "dji_ts_ms": base, "direction": "up",
        "topic": "sys/product/TEST_DOCK_01/status", "payload": {"sub_type": 0},
    }]
    for lk in links:
        ts = base + lk["dt_ms"]
        if lk.get("no_wl"):
            data = {"gps": {}}
        else:
            wl = {}
            if "sdr" in lk:
                wl["sdr_quality"] = lk["sdr"]
            if "4g" in lk:
                wl["4g_quality"] = lk["4g"]
            data = {"gps": {}, "wireless_link": wl}
        frames.append({
            "recv_ts_ms": ts, "dji_ts_ms": ts, "direction": "up",
            "topic": "thing/product/TEST_DOCK_01/drc/up",
            "payload": {"method": "drc_geo_connect_info_push", "data": data},
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


def test_collect_link_samples_basic(tmp_path: pathlib.Path) -> None:
    rec = _make_recording(tmp_path, [
        {"dt_ms": 1000, "sdr": 5, "4g": 0},
        {"dt_ms": 2000, "sdr": 0, "4g": 3},
    ])
    rep = collect(rec, _seed_config(tmp_path))
    assert len(rep.link_samples) == 2
    s0, s1 = rep.link_samples
    assert isinstance(s0, LinkSample)
    assert (s0.rel_ms, s0.sdr_quality, s0.fourg_quality) == (1000, 5, 0)
    assert (s1.sdr_quality, s1.fourg_quality) == (0, 3)


def test_collect_link_missing_field_none(tmp_path: pathlib.Path) -> None:
    rec = _make_recording(tmp_path, [{"dt_ms": 1000, "sdr": 5}])  # 无 4g
    rep = collect(rec, _seed_config(tmp_path))
    assert len(rep.link_samples) == 1
    assert rep.link_samples[0].sdr_quality == 5
    assert rep.link_samples[0].fourg_quality is None


def test_collect_link_no_wireless_link_skipped(tmp_path: pathlib.Path) -> None:
    rec = _make_recording(tmp_path, [{"dt_ms": 1000, "no_wl": True}])
    rep = collect(rec, _seed_config(tmp_path))
    assert rep.link_samples == []
