"""ReplaySource — 读 sim_dji_cloud_service 录制目录 (设计 §0.4 / §3.4).

输入: recordings/<sn>_<ts>/  目录, 含 manifest.json + topics/*.jsonl
输出: 按 recv_ts_ms 单调升序的 Envelope 流

- 使用 heapq k-way merge, 内存占用 O(N_files), 与录制大小无关.
- speed=1.0 按原速 sleep, speed=0 尽可能快 (CI/分析模式).
- drop_drc=True 默认丢 drc/up + drc/down (高频噪声).
- 未知 topic (不在 TOPIC_TEMPLATES) 跳过, 不会抛错.
"""

from __future__ import annotations

import asyncio
import heapq
import json
import pathlib
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass

from dock_guard.ingest.source import Envelope, parse_topic
from dock_guard.types import TopicKey


@dataclass(frozen=True, slots=True)
class RecordingManifest:
    """manifest.json 的最小解析视图."""

    schema_version: int
    dock_sn: str
    drone_sn: str | None
    started_at_recv_ms: int
    ended_at_recv_ms: int
    jsonl_files: tuple[pathlib.Path, ...]


def _load_manifest(recording_dir: pathlib.Path) -> RecordingManifest:
    manifest_path = recording_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json not found in {recording_dir}")
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))

    schema_version = int(raw.get("schema_version", 0))
    if schema_version != 1:
        raise ValueError(
            f"unsupported manifest schema_version={schema_version} (expected 1)"
        )

    dock_sn = str(raw["dock_sn"])
    drone_sn_raw = raw.get("drone_sn")
    drone_sn = str(drone_sn_raw) if drone_sn_raw else None

    files: list[pathlib.Path] = []
    for t in raw.get("topics", []):
        for f in t.get("files", []):
            rel = f.get("name")
            if not rel:
                continue
            files.append(recording_dir / rel)

    return RecordingManifest(
        schema_version=schema_version,
        dock_sn=dock_sn,
        drone_sn=drone_sn,
        started_at_recv_ms=int(raw["started_at_recv_ms"]),
        ended_at_recv_ms=int(raw["ended_at_recv_ms"]),
        jsonl_files=tuple(files),
    )


def _iter_jsonl_envelopes(
    path: pathlib.Path,
    *,
    dock_sn: str,
    drone_sn: str | None,
) -> Iterator[Envelope]:
    """单个 jsonl 文件 → Envelope 迭代器. 未知 topic 静默跳过."""
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            line = raw_line.rstrip("\n")
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{line_no} invalid json: {e}") from e

            topic = row["topic"]
            parsed = parse_topic(topic, dock_sn=dock_sn, drone_sn=drone_sn)
            if parsed is None:
                continue  # 未知 topic (如 events_reply 不在 v2 TOPIC_TEMPLATES)
            topic_key, dk_sn, dr_sn = parsed

            dji_ts_raw = row.get("dji_ts_ms")
            yield Envelope(
                recv_ts_ms=int(row["recv_ts_ms"]),
                dji_ts_ms=int(dji_ts_raw) if dji_ts_raw is not None else None,
                direction=str(row["direction"]),
                topic=topic,
                payload=row["payload"],
                topic_key=topic_key,
                dock_sn=dk_sn,
                drone_sn=dr_sn,
            )


class ReplaySource:
    """实现 Source 协议."""

    def __init__(
        self,
        recording_dir: pathlib.Path,
        *,
        speed: float = 1.0,
        drop_drc: bool = True,
        drop_topics: frozenset[TopicKey] = frozenset(),
    ) -> None:
        if speed < 0:
            raise ValueError(f"speed must be >= 0, got {speed}")
        self.recording_dir = recording_dir
        self.speed = speed
        self.drop_drc = drop_drc
        self.drop_topics = drop_topics
        self.manifest = _load_manifest(recording_dir)

    @property
    def dock_sn(self) -> str:
        return self.manifest.dock_sn

    @property
    def drone_sn(self) -> str | None:
        return self.manifest.drone_sn

    def _should_drop(self, env: Envelope) -> bool:
        if env.topic_key in self.drop_topics:
            return True
        if self.drop_drc and env.topic_key in (TopicKey.DOCK_DRC_UP, TopicKey.DOCK_DRC_DOWN):
            return True
        return False

    def _merged_iter(self) -> Iterator[Envelope]:
        """k-way merge 多个 jsonl 按 recv_ts_ms 单调升序."""
        iters = [
            _iter_jsonl_envelopes(
                p, dock_sn=self.manifest.dock_sn, drone_sn=self.manifest.drone_sn
            )
            for p in self.manifest.jsonl_files
            if p.exists()
        ]
        for env in heapq.merge(*iters, key=lambda e: e.recv_ts_ms):
            if self._should_drop(env):
                continue
            yield env

    async def __aiter__(self) -> AsyncIterator[Envelope]:
        first_recv_ts: int | None = None
        wall_start_s: float | None = None

        for env in self._merged_iter():
            if self.speed > 0:
                if first_recv_ts is None:
                    first_recv_ts = env.recv_ts_ms
                    wall_start_s = time.monotonic()
                else:
                    assert wall_start_s is not None
                    target_offset_s = (env.recv_ts_ms - first_recv_ts) / 1000.0 / self.speed
                    elapsed_s = time.monotonic() - wall_start_s
                    sleep_s = target_offset_s - elapsed_s
                    if sleep_s > 0.001:
                        await asyncio.sleep(sleep_s)
            yield env

    async def close(self) -> None:
        # 无长期句柄需要释放; 每个文件由 _iter_jsonl_envelopes 的 with 自动关闭.
        return None
