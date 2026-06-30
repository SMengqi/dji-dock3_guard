"""Stage 4-E Task 1: collector 指标提取单测.

不依赖 sim 录制. 用合成 envelope 驱动整条流水线 (DockAggregator + RuleEngine +
AlertCoordinator), 验证 collector 把 peak_wind / min_battery / verdicts 计得对.
"""

from __future__ import annotations

import json
import pathlib
import textwrap

import pytest

from dock_guard.analytics import collect
from dock_guard.analytics.models import SCHEMA_VERSION, FlightReport


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


def _make_recording(tmp_path: pathlib.Path, frames: list[dict]) -> pathlib.Path:
    rec = tmp_path / "synthetic_rec"
    rec.mkdir()
    (rec / "topics").mkdir()
    with (rec / "topics" / "x.jsonl").open("w", encoding="utf-8") as f:
        for fr in frames:
            f.write(json.dumps({
                "recv_ts_ms": fr["recv_ts_ms"],
                "dji_ts_ms": fr.get("dji_ts_ms", fr["recv_ts_ms"]),
                "direction": "up",
                "topic": fr["topic"],
                "payload": fr["payload"],
            }) + "\n")
    (rec / "manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "dock_sn": "TEST_DOCK_01",
        "drone_sn": "TEST_DRONE_01",
        "started_at_recv_ms": frames[0]["recv_ts_ms"],
        "ended_at_recv_ms": frames[-1]["recv_ts_ms"],
        "topics": [{
            "topic": "synthetic",
            "device_sn": "TEST_DOCK_01",
            "direction": "up",
            "count": len(frames),
            "first_recv_ts_ms": frames[0]["recv_ts_ms"],
            "last_recv_ts_ms": frames[-1]["recv_ts_ms"],
            "files": [{
                "name": "topics/x.jsonl",
                "count": len(frames),
                "first_ms": frames[0]["recv_ts_ms"],
                "last_ms": frames[-1]["recv_ts_ms"],
            }],
        }],
    }), encoding="utf-8")
    return rec


def _flight_sequence() -> list[dict]:
    """合成 dock OSD (wind/tilt/rain) + drone OSD (battery)."""
    base = 1700000000000
    return [
        {"recv_ts_ms": base, "topic": "sys/product/TEST_DOCK_01/status",
         "payload": {"sub_type": 0}},
        {"recv_ts_ms": base + 200, "topic": "thing/product/TEST_DOCK_01/osd",
         "payload": {"data": {
             "flighttask_step_code": 1, "drone_in_dock": 1,
             "wind_speed": 5.0,
             "tilt_angle": {"valid": 1, "value": 0.6},
             "rainfall": 1,
             "sub_device": {"device_sn": "TEST_DRONE_01"},
         }, "timestamp": base + 200}},
        {"recv_ts_ms": base + 300, "topic": "thing/product/TEST_DRONE_01/osd",
         "payload": {"data": {
             "mode_code": 0, "height": 0.0,
             "battery": {"capacity_percent": 42},
         }, "timestamp": base + 300}},
        # 第二帧风更大 / 电更低
        {"recv_ts_ms": base + 5000, "topic": "thing/product/TEST_DOCK_01/osd",
         "payload": {"data": {"wind_speed": 7.5}, "timestamp": base + 5000}},
        {"recv_ts_ms": base + 5100, "topic": "thing/product/TEST_DRONE_01/osd",
         "payload": {"data": {"battery": {"capacity_percent": 30}},
                     "timestamp": base + 5100}},
    ]


class TestEmptyRecording:
    def test_single_frame_returns_report_with_none_metrics(
        self, tmp_path: pathlib.Path
    ) -> None:
        cfg = _seed_config(tmp_path)
        rec = _make_recording(tmp_path, [
            {"recv_ts_ms": 1000, "topic": "sys/product/TEST_DOCK_01/status",
             "payload": {"sub_type": 0}},
        ])
        rep = collect(rec, cfg)
        assert isinstance(rep, FlightReport)
        assert rep.schema_version == SCHEMA_VERSION
        assert rep.total_envelopes == 1
        assert rep.metrics.peak_wind_gust_30s is None
        assert rep.metrics.min_battery_percent is None
        # 单帧 sys/status 仅触发 WARMING_UP 类规则; verdict count 不应爆炸
        assert rep.metrics.total_verdicts < 10


class TestMetricsExtraction:
    def test_peak_wind_gust_tracked(self, tmp_path: pathlib.Path) -> None:
        cfg = _seed_config(tmp_path)
        rec = _make_recording(tmp_path, _flight_sequence())
        rep = collect(rec, cfg)
        assert rep.metrics.peak_wind_gust_30s == pytest.approx(7.5, abs=0.5)
        assert rep.metrics.peak_wind_gust_30s_at_ms is not None
        assert rep.metrics.peak_wind_gust_30s_at_ms >= 1700000000000 + 5000

    def test_min_battery_tracked(self, tmp_path: pathlib.Path) -> None:
        cfg = _seed_config(tmp_path)
        rec = _make_recording(tmp_path, _flight_sequence())
        rep = collect(rec, cfg)
        assert rep.metrics.min_battery_percent == 30
        assert rep.metrics.min_battery_percent_at_ms is not None
        assert rep.metrics.min_battery_percent_at_ms >= 1700000000000 + 5100

    def test_verdicts_by_code_aggregated(self, tmp_path: pathlib.Path) -> None:
        """合成飞行序列应触发至少一个 verdict (具体 code 与 rule 阈值耦合, 仅检大类)."""
        cfg = _seed_config(tmp_path)
        rec = _make_recording(tmp_path, _flight_sequence())
        rep = collect(rec, cfg)
        assert rep.metrics.total_verdicts >= 1
        assert len(rep.metrics.verdicts_by_code) >= 1

    def test_total_envelopes_matches_input(self, tmp_path: pathlib.Path) -> None:
        cfg = _seed_config(tmp_path)
        frames = _flight_sequence()
        rec = _make_recording(tmp_path, frames)
        rep = collect(rec, cfg)
        assert rep.total_envelopes == len(frames)

    def test_started_ended_at_ms_set(self, tmp_path: pathlib.Path) -> None:
        cfg = _seed_config(tmp_path)
        frames = _flight_sequence()
        rec = _make_recording(tmp_path, frames)
        rep = collect(rec, cfg)
        assert rep.started_at_ms == frames[0]["recv_ts_ms"]
        assert rep.ended_at_ms == frames[-1]["recv_ts_ms"]
        assert rep.duration_ms == rep.ended_at_ms - rep.started_at_ms

    def test_dock_sn_from_manifest(self, tmp_path: pathlib.Path) -> None:
        cfg = _seed_config(tmp_path)
        rec = _make_recording(tmp_path, _flight_sequence())
        rep = collect(rec, cfg)
        assert rep.dock_sn == "TEST_DOCK_01"


class TestOfflineDuration:
    def test_no_offline_mid_flight(self, tmp_path: pathlib.Path) -> None:
        """合成序列无 OFFLINE 中断; 启动期 OFFLINE (在第一帧前) 可能存在但应 < 1s."""
        cfg = _seed_config(tmp_path)
        rec = _make_recording(tmp_path, _flight_sequence())
        rep = collect(rec, cfg)
        assert rep.metrics.longest_offline_ms < 1000


class TestSerialization:
    def test_to_dict_is_json_safe(self, tmp_path: pathlib.Path) -> None:
        cfg = _seed_config(tmp_path)
        rec = _make_recording(tmp_path, _flight_sequence())
        rep = collect(rec, cfg)
        d = rep.to_dict()
        s = json.dumps(d)
        d2 = json.loads(s)
        assert d2["schema_version"] == SCHEMA_VERSION
        assert d2["dock_sn"] == d["dock_sn"]
        assert d2["metrics"]["total_verdicts"] == d["metrics"]["total_verdicts"]

    def test_to_dict_metrics_flattened(self, tmp_path: pathlib.Path) -> None:
        """metrics 序列化后是平铺 dict, 含全部 10 个字段."""
        cfg = _seed_config(tmp_path)
        rec = _make_recording(tmp_path, _flight_sequence())
        rep = collect(rec, cfg)
        d = rep.to_dict()
        assert isinstance(d["metrics"], dict)
        for key in ("peak_wind_gust_30s", "peak_wind_gust_30s_at_ms",
                    "min_battery_percent", "min_battery_percent_at_ms",
                    "longest_offline_ms", "flight_duration_ms",
                    "total_verdicts", "total_dispatched", "total_suppressed",
                    "verdicts_by_code"):
            assert key in d["metrics"]


def _speed_sequence() -> list[dict]:
    """单帧 drone OSD 同时带 battery + height + wind_speed + 水平/垂直速度,
    确保落一条 battery_sample 且带速度."""
    base = 1700000000000
    return [
        {"recv_ts_ms": base, "topic": "sys/product/TEST_DOCK_01/status",
         "payload": {"sub_type": 0}},
        {"recv_ts_ms": base + 200, "topic": "thing/product/TEST_DOCK_01/osd",
         "payload": {"data": {
             "flighttask_step_code": 1, "drone_in_dock": 0,
             "sub_device": {"device_sn": "TEST_DRONE_01"},
         }, "timestamp": base + 200}},
        {"recv_ts_ms": base + 300, "topic": "thing/product/TEST_DRONE_01/osd",
         "payload": {"data": {
             "mode_code": 0, "height": 30.0,
             "wind_speed": 40,            # drone OSD 0.1 m/s -> 4.0 m/s
             "wind_direction": 3,
             "horizontal_speed": 8.5,
             "vertical_speed": -1.2,
             "battery": {"capacity_percent": 80},
         }, "timestamp": base + 300}},
    ]


class TestSpeedSampling:
    def test_battery_sample_carries_speed(self, tmp_path: pathlib.Path) -> None:
        cfg = _seed_config(tmp_path)
        rec = _make_recording(tmp_path, _speed_sequence())
        rep = collect(rec, cfg)
        assert rep.battery_samples, "expected at least one battery_sample"
        s = rep.battery_samples[0]
        assert s.horizontal_speed_ms == pytest.approx(8.5)
        assert s.vertical_speed_ms == pytest.approx(-1.2)

    def test_speed_none_when_absent(self, tmp_path: pathlib.Path) -> None:
        cfg = _seed_config(tmp_path)
        seq = _speed_sequence()
        del seq[2]["payload"]["data"]["horizontal_speed"]
        del seq[2]["payload"]["data"]["vertical_speed"]
        rec = _make_recording(tmp_path, seq)
        rep = collect(rec, cfg)
        assert rep.battery_samples, "expected at least one battery_sample"
        s = rep.battery_samples[0]
        assert s.horizontal_speed_ms is None
        assert s.vertical_speed_ms is None
