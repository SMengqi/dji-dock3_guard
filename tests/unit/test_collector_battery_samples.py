"""Stage 5-F Task 1: collector 采 battery_samples 单测.

谁运行: pytest discover. 同义文件: 无. 数据: 合成 60s 录制 (sim manifest v1 schema).
用户指令: "ok" (T1 开工).
"""

from __future__ import annotations

import json
import pathlib
import textwrap

import pytest

from dock_guard.analytics import collect
from dock_guard.analytics.models import SCHEMA_VERSION, BatterySample


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


def _make_long_recording(tmp_path: pathlib.Path, duration_s: int = 60) -> pathlib.Path:
    """合成 N 秒录制: 每秒 dock OSD + drone OSD (含 battery 单调下降)."""
    rec = tmp_path / "synthetic_rec"
    rec.mkdir()
    (rec / "topics").mkdir()
    base = 1700000000000
    frames = [{
        "recv_ts_ms": base, "dji_ts_ms": base, "direction": "up",
        "topic": "sys/product/TEST_DOCK_01/status",
        "payload": {"sub_type": 0},
    }]
    for t in range(duration_s):
        ts = base + t * 1000
        frames.append({
            "recv_ts_ms": ts + 100, "dji_ts_ms": ts + 100, "direction": "up",
            "topic": "thing/product/TEST_DOCK_01/osd",
            "payload": {"data": {
                "wind_speed": 4.0 + (t % 5) * 0.5,
                "flighttask_step_code": 5, "drone_in_dock": 0,
                "sub_device": {"device_sn": "TEST_DRONE_01"},
            }, "timestamp": ts + 100},
        })
        frames.append({
            "recv_ts_ms": ts + 200, "dji_ts_ms": ts + 200, "direction": "up",
            "topic": "thing/product/TEST_DRONE_01/osd",
            "payload": {"data": {
                "mode_code": 5, "height": 30.0 + t * 0.5,
                "battery": {"capacity_percent": 100 - t},
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
            "files": [{
                "name": "topics/x.jsonl", "count": len(frames),
                "first_ms": frames[0]["recv_ts_ms"],
                "last_ms": frames[-1]["recv_ts_ms"],
            }],
        }],
    }), encoding="utf-8")
    return rec


class TestSchemaV3:
    def test_schema_version_is_3(self) -> None:
        assert SCHEMA_VERSION == 3


class TestBatterySamples:
    def test_samples_collected_around_10s_cadence(self, tmp_path: pathlib.Path) -> None:
        """60s 录制 -> ~6 个样本 (10s 一次), +/- 1 容差."""
        cfg = _seed_config(tmp_path)
        rec = _make_long_recording(tmp_path, 60)
        rep = collect(rec, cfg)
        assert 5 <= len(rep.battery_samples) <= 8

    def test_sample_fields_typed(self, tmp_path: pathlib.Path) -> None:
        cfg = _seed_config(tmp_path)
        rec = _make_long_recording(tmp_path, 60)
        rep = collect(rec, cfg)
        for s in rep.battery_samples:
            assert isinstance(s, BatterySample)
            assert 0 <= s.percent <= 100
            assert s.rel_ms >= 0
            assert s.height_m >= 0
            assert s.wind_ms >= 0

    def test_samples_monotonic_time(self, tmp_path: pathlib.Path) -> None:
        cfg = _seed_config(tmp_path)
        rec = _make_long_recording(tmp_path, 60)
        rep = collect(rec, cfg)
        ts = [s.rel_ms for s in rep.battery_samples]
        assert ts == sorted(ts)

    def test_to_dict_json_safe(self, tmp_path: pathlib.Path) -> None:
        cfg = _seed_config(tmp_path)
        rec = _make_long_recording(tmp_path, 30)
        rep = collect(rec, cfg)
        d = rep.to_dict()
        assert d["schema_version"] == 3
        assert "battery_samples" in d
        # JSON safe
        json.dumps(d)
        # 每个 sample 含 4 字段
        for s in d["battery_samples"]:
            assert {"rel_ms", "percent", "height_m", "wind_ms"} <= set(s.keys())
