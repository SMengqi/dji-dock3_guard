"""Phase 2 单元测试: Envelope + parse_topic."""

from __future__ import annotations

import pytest

from dock_guard.ingest.source import Envelope, parse_topic
from dock_guard.types import TopicKey


class TestParseTopic:
    def test_dock_osd(self) -> None:
        r = parse_topic(
            "thing/product/8UUXN7N00A0GAA/osd",
            dock_sn="8UUXN7N00A0GAA",
            drone_sn="1581F8HGX257Q00A0PSH",
        )
        assert r is not None
        key, dock_sn, drone_sn = r
        assert key == TopicKey.DOCK_OSD
        assert dock_sn == "8UUXN7N00A0GAA"
        assert drone_sn is None  # dock_* 类不填 drone_sn

    def test_drone_osd(self) -> None:
        r = parse_topic(
            "thing/product/1581F8HGX257Q00A0PSH/osd",
            dock_sn="8UUXN7N00A0GAA",
            drone_sn="1581F8HGX257Q00A0PSH",
        )
        assert r is not None
        key, _, drone_sn = r
        assert key == TopicKey.DRONE_OSD
        assert drone_sn == "1581F8HGX257Q00A0PSH"

    def test_dock_drc_up(self) -> None:
        r = parse_topic(
            "thing/product/8UUXN7N00A0GAA/drc/up",
            dock_sn="8UUXN7N00A0GAA",
            drone_sn=None,
        )
        assert r is not None
        assert r[0] == TopicKey.DOCK_DRC_UP

    def test_sys_status(self) -> None:
        r = parse_topic(
            "sys/product/8UUXN7N00A0GAA/status",
            dock_sn="8UUXN7N00A0GAA",
            drone_sn=None,
        )
        assert r is not None
        assert r[0] == TopicKey.DOCK_SYS_STATUS

    def test_unknown_topic(self) -> None:
        # events_reply 不在 v2 TOPIC_TEMPLATES
        r = parse_topic(
            "thing/product/8UUXN7N00A0GAA/events_reply",
            dock_sn="8UUXN7N00A0GAA",
            drone_sn=None,
        )
        assert r is None

    def test_drone_topic_without_drone_sn_returns_none(self) -> None:
        # 设计 §15.1.1 #3: drone_sn 未知时 drone_* 类跳过
        r = parse_topic(
            "thing/product/1581F8HGX257Q00A0PSH/osd",
            dock_sn="8UUXN7N00A0GAA",
            drone_sn=None,
        )
        assert r is None

    def test_wrong_sn_returns_none(self) -> None:
        r = parse_topic(
            "thing/product/UNKNOWN_SN/osd",
            dock_sn="8UUXN7N00A0GAA",
            drone_sn="1581F8HGX257Q00A0PSH",
        )
        assert r is None


class TestEnvelope:
    def test_frozen(self) -> None:
        env = Envelope(
            recv_ts_ms=1780000000000,
            dji_ts_ms=1780000000000,
            direction="up",
            topic="thing/product/SN/osd",
            payload={"a": 1},
            topic_key=TopicKey.DOCK_OSD,
            dock_sn="SN",
            drone_sn=None,
        )
        with pytest.raises(AttributeError):
            env.recv_ts_ms = 0  # type: ignore[misc]

    def test_drone_sn_required_only_for_drone_topics(self) -> None:
        env = Envelope(
            recv_ts_ms=1, dji_ts_ms=1, direction="up",
            topic="thing/product/SN/osd", payload={},
            topic_key=TopicKey.DOCK_OSD, dock_sn="SN", drone_sn=None,
        )
        assert env.drone_sn is None
