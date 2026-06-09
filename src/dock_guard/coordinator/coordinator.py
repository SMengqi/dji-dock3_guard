"""AlertCoordinator — 三闸串行 + AlertSink (设计 §6)."""

from __future__ import annotations

import dataclasses
import json
import pathlib
from collections.abc import Iterable
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from dock_guard.config import AppConfig
from dock_guard.coordinator.alert_record import AlertRecord, Decision
from dock_guard.coordinator.cooldown import CooldownGate
from dock_guard.coordinator.dedup import DedupGate, DedupStatus
from dock_guard.coordinator.mute import MuteState
from dock_guard.rules.verdict import Verdict

if TYPE_CHECKING:
    from dock_guard.notify.bus import NotificationBus


@runtime_checkable
class AlertSink(Protocol):
    def write(self, record: AlertRecord) -> None: ...
    def close(self) -> None: ...


class NullAlertSink:
    """测试/dev 用. 写到 list."""

    def __init__(self) -> None:
        self.records: list[AlertRecord] = []

    def write(self, record: AlertRecord) -> None:
        self.records.append(record)

    def close(self) -> None:
        return None


class JsonlAlertSink:
    """简单追加写 alerts.jsonl. Phase 9 替换为带轮转的版本."""

    def __init__(self, path: pathlib.Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._fh = path.open("a", encoding="utf-8")

    def write(self, record: AlertRecord) -> None:
        line = json.dumps(record.to_dict(), ensure_ascii=False, separators=(",", ":"))
        self._fh.write(line)
        self._fh.write("\n")
        self._fh.flush()

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()


class AlertCoordinator:
    """每 dock 一个实例."""

    def __init__(
        self,
        cfg: AppConfig,
        *,
        sink: AlertSink | None = None,
        bus: NotificationBus | None = None,
    ) -> None:
        params = cfg.alert_levels.coordinator
        self.cooldown = CooldownGate(params)
        self.dedup = DedupGate(params)
        self.mute = MuteState()
        self.sink: AlertSink = sink or NullAlertSink()
        self.bus: NotificationBus | None = bus

    def handle_batch(self, verdicts: Iterable[Verdict]) -> list[AlertRecord]:
        # §6.6: level 降序, 同级别按 code 字典序
        ordered = sorted(verdicts, key=lambda v: (-v.level.value, v.code))
        return [self.handle(v) for v in ordered]

    async def handle_batch_async(
        self, verdicts: Iterable[Verdict]
    ) -> list[AlertRecord]:
        """同 handle_batch, 但 DISPATCHED 时调用 NotificationBus.dispatch 填充 channels."""
        from dock_guard.notify.notification import Notification

        ordered = sorted(verdicts, key=lambda v: (-v.level.value, v.code))
        out: list[AlertRecord] = []
        for v in ordered:
            record = self._run_gates(v)
            if record.decision == Decision.DISPATCHED and self.bus is not None:
                notif = Notification.from_alert_record(record)
                channels = await self.bus.dispatch(notif)
                # 重建 record (frozen) 加 channels
                record = dataclasses.replace(record, channels=channels)
            self.sink.write(record)
            out.append(record)
        return out

    def handle(self, verdict: Verdict) -> AlertRecord:
        """同步入口. 不触发 bus.dispatch (无 await). bus 集成必须用 handle_batch_async."""
        record = self._run_gates(verdict)
        self.sink.write(record)
        return record

    def _run_gates(self, verdict: Verdict) -> AlertRecord:
        gates: dict[str, str] = {}
        decision: Decision = Decision.DISPATCHED

        cd = self.cooldown.check_and_record(verdict)
        gates["cooldown"] = cd
        if cd != "pass":
            return self._build_record(verdict, Decision.SUPPRESSED, gates)

        dd = self.dedup.check_and_record(verdict)
        gates["dedup"] = dd.value
        if dd == DedupStatus.COALESCED:
            return self._build_record(verdict, Decision.SUPPRESSED, gates)

        mute_status = self.mute.check(verdict, now_ms=verdict.ts_ms)
        gates["mute"] = mute_status
        if mute_status != "pass":
            return self._build_record(verdict, Decision.SUPPRESSED, gates)

        return self._build_record(verdict, decision, gates)

    @staticmethod
    def _build_record(
        verdict: Verdict, decision: Decision, gates: dict[str, str]
    ) -> AlertRecord:
        return AlertRecord(
            ts_ms=verdict.ts_ms,
            verdict=verdict,
            decision=decision,
            gates=gates,
        )

    def close(self) -> None:
        self.sink.close()
