"""Phase 2 集成测试: ReplaySource 跑兄弟服务的录制目录.

依赖 tests/conftest.py 的 recording fixture, 解析到
../sim_dji_cloud_service/sim_dji_cloud/recordings/<sn>_<ts>/
若兄弟服务未 check out 则 skip.
"""

from __future__ import annotations

import pathlib
from collections import Counter

import pytest

from dock_guard.ingest import ReplaySource
from dock_guard.types import TopicKey

pytestmark = pytest.mark.integration


async def test_replay_default_sample_iterates_to_end(recording: pathlib.Path) -> None:
    src = ReplaySource(recording, speed=0.0)
    assert src.dock_sn == "8UUXN7N00A0GAA"
    assert src.drone_sn == "1581F8HGX257Q00A0PSH"

    counts: Counter[TopicKey] = Counter()
    last_ts: int | None = None
    async for env in src:
        if last_ts is not None:
            assert env.recv_ts_ms >= last_ts, "envelope 时间戳必须单调升序"
        last_ts = env.recv_ts_ms
        counts[env.topic_key] += 1
    await src.close()

    # 与 manifest 中各 topic count 对齐 (drc/up + drc/down 默认丢弃)
    assert counts[TopicKey.DOCK_OSD] == 818
    assert counts[TopicKey.DRONE_OSD] == 206
    assert counts[TopicKey.DOCK_EVENTS] == 995
    assert counts[TopicKey.DRONE_EVENTS] == 201
    assert counts[TopicKey.DOCK_STATE] == 6
    assert counts[TopicKey.DRONE_STATE] == 148
    assert counts[TopicKey.DOCK_REQUESTS] == 6
    assert counts[TopicKey.DOCK_REQUESTS_REPLY] == 12
    assert counts[TopicKey.DOCK_SERVICES_REPLY] == 125
    assert counts[TopicKey.DRONE_STATE_REPLY] == 97
    assert counts[TopicKey.DOCK_SERVICES] == 125
    assert counts.get(TopicKey.DOCK_DRC_UP, 0) == 0
    assert counts.get(TopicKey.DOCK_DRC_DOWN, 0) == 0


async def test_drop_drc_off_includes_drc(recording: pathlib.Path) -> None:
    src = ReplaySource(recording, speed=0.0, drop_drc=False)
    counts: Counter[TopicKey] = Counter()
    async for env in src:
        counts[env.topic_key] += 1
    # 样本含 12626 条 drc/up + 569 条 drc/down
    assert counts[TopicKey.DOCK_DRC_UP] == 12626
    assert counts[TopicKey.DOCK_DRC_DOWN] == 569


async def test_drop_topics_filter(recording: pathlib.Path) -> None:
    src = ReplaySource(
        recording,
        speed=0.0,
        drop_topics=frozenset({TopicKey.DOCK_OSD, TopicKey.DRONE_OSD}),
    )
    counts: Counter[TopicKey] = Counter()
    async for env in src:
        counts[env.topic_key] += 1
    assert counts.get(TopicKey.DOCK_OSD, 0) == 0
    assert counts.get(TopicKey.DRONE_OSD, 0) == 0
    assert counts[TopicKey.DOCK_EVENTS] == 995


async def test_invalid_manifest_path(tmp_path: pathlib.Path) -> None:
    with pytest.raises(FileNotFoundError):
        ReplaySource(tmp_path)


async def test_negative_speed_rejected(recording: pathlib.Path) -> None:
    with pytest.raises(ValueError):
        ReplaySource(recording, speed=-1.0)
