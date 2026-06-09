"""DockAggregator — per (dock+drone) 状态中心 (设计 §4.1)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from dock_guard.aggregator.facts import F, FrozenFacts, freeze_facts
from dock_guard.aggregator.facts_ring import FactsRing
from dock_guard.aggregator.phase_machine import PhaseResolution, resolve_phase
from dock_guard.aggregator.windows import TimeBoundedDeque
from dock_guard.config import AppConfig
from dock_guard.ingest.source import Envelope
from dock_guard.types import (
    EmergencyStopState,
    Phase,
    PhaseSource,
    RtkFixedCode,
    TopicKey,
)


@dataclass(frozen=True, slots=True)
class PhaseTransition:
    """阶段或真值源切换审计 (设计 §4.3)."""

    ts_ms: int
    dock_sn: str
    phase_from: Phase
    phase_to: Phase
    phase_source_from: PhaseSource
    phase_source_to: PhaseSource
    reason: str
    drone_height: float | None
    mode_code: int | None
    drone_in_dock: int | None
    warnings: tuple[str, ...]


class DockAggregator:
    """per (dock+drone) 状态中心.

    apply() 顺序: 按 envelope 的 recv_ts_ms 升序调用; 任何乱序帧由 ingest 层丢弃.
    """

    def __init__(self, dock_sn: str, config: AppConfig) -> None:
        self.dock_sn = dock_sn
        self.drone_sn: str | None = None
        self.config = config

        self._dock_fields: dict[str, Any] = {}
        self._drone_fields: dict[str, Any] = {}

        self._last_dock_osd_ts: int = 0
        self._last_drone_osd_ts: int = 0
        self._last_flighttask_progress_ts: int = 0
        self._last_sys_status_ts: int = 0
        self._sys_online: bool = True
        self._now_ms: int = 0

        self._wind_gust_max_30s = TimeBoundedDeque(window_ms=30000)

        self.facts_ring = FactsRing(
            max_window_ms=config.runtime.runtime.facts_ring_window_max_ms
        )

        self._current_phase: Phase = Phase.OFFLINE
        self._current_phase_source: PhaseSource = PhaseSource.FALLBACK_IDLE
        self._phase_transitions: list[PhaseTransition] = []

        self._started_at_ms: int = 0
        self._warming_up_ms: int = config.runtime.runtime.warming_up_ms

        self._seen_safety_fields: set[str] = set()

    # ──────────────────────────────────────────────────────────────
    # 公共 API
    # ──────────────────────────────────────────────────────────────

    def apply(self, env: Envelope) -> None:
        """主入口."""
        if self._started_at_ms == 0:
            self._started_at_ms = env.recv_ts_ms
        self._now_ms = env.recv_ts_ms

        if self.drone_sn is None and env.drone_sn is not None:
            self.drone_sn = env.drone_sn

        self._dispatch(env)
        self._update_phase(env.recv_ts_ms)
        self._snapshot_facts(env.recv_ts_ms)

    def latest_facts(self) -> FrozenFacts | None:
        return self.facts_ring.latest()

    def drain_phase_transitions(self) -> Iterator[PhaseTransition]:
        out, self._phase_transitions = self._phase_transitions, []
        yield from out

    @property
    def current_phase(self) -> Phase:
        return self._current_phase

    @property
    def current_phase_source(self) -> PhaseSource:
        return self._current_phase_source

    @property
    def warming_up(self) -> bool:
        if self._started_at_ms == 0:
            return True
        return (self._now_ms - self._started_at_ms) < self._warming_up_ms

    # ──────────────────────────────────────────────────────────────
    # 内部 dispatch
    # ──────────────────────────────────────────────────────────────

    def _dispatch(self, env: Envelope) -> None:
        data = env.payload.get("data", {}) if isinstance(env.payload, dict) else {}
        if not isinstance(data, dict):
            data = {}

        if env.topic_key == TopicKey.DOCK_OSD:
            self._apply_dock_osd(env.recv_ts_ms, data)
        elif env.topic_key == TopicKey.DRONE_OSD:
            self._apply_drone_osd(env.recv_ts_ms, data)
        elif env.topic_key == TopicKey.DOCK_SYS_STATUS:
            self._apply_sys_status(env.recv_ts_ms, env.payload)
        elif env.topic_key == TopicKey.DOCK_EVENTS:
            self._apply_dock_events(env.recv_ts_ms, env.payload)

    def _apply_dock_osd(self, recv_ts_ms: int, data: dict[str, Any]) -> None:
        """dock OSD 双类消息按字段 latest 合并 (设计 §4.6)."""
        self._last_dock_osd_ts = recv_ts_ms

        for k, v in data.items():
            self._dock_fields[k] = v

        if "emergency_stop_state" in data:
            self._dock_fields["emergency_stop_pressed"] = (
                data["emergency_stop_state"] == EmergencyStopState.ENABLE.value
            )

        for field_name in (
            "cover_state", "putter_state", "emergency_stop_state",
            "rainfall", "temperature", "environment_temperature",
            "wind_speed", "tilt_angle", "flighttask_step_code", "drone_in_dock",
        ):
            if field_name in data:
                self._seen_safety_fields.add(field_name)

        ws = data.get("wind_speed")
        if isinstance(ws, (int, float)):
            self._wind_gust_max_30s.push(recv_ts_ms, float(ws))

    def _apply_drone_osd(self, recv_ts_ms: int, data: dict[str, Any]) -> None:
        self._last_drone_osd_ts = recv_ts_ms

        for k, v in data.items():
            self._drone_fields[k] = v

        position_state = data.get("position_state")
        if isinstance(position_state, dict) and "is_fixed" in position_state:
            self._drone_fields["rtk_is_fixed_code"] = position_state["is_fixed"]
            self._drone_fields["rtk_fixed"] = (
                position_state["is_fixed"] == RtkFixedCode.FIXING_SUCCESSFUL.value
            )

        battery = data.get("battery")
        if isinstance(battery, dict):
            for bf in ("capacity_percent", "return_home_power", "landing_power",
                       "remain_flight_time"):
                if bf in battery:
                    self._drone_fields[f"battery_{bf}"] = battery[bf]

        # drone OSD wind_speed 单位为 0.1 m/s (整数), 与 dock 端 m/s float 不同.
        # 设计 §3.2.1 列的 "float m/s" 与样本观测有出入, 这里统一归一为 m/s.
        ws = data.get("wind_speed")
        if isinstance(ws, (int, float)):
            ws_mps = float(ws) / 10.0
            self._drone_fields["wind_speed"] = ws_mps   # 覆盖为 m/s
            self._wind_gust_max_30s.push(recv_ts_ms, ws_mps)

        for field_name in (
            "mode_code", "height", "battery", "wind_speed", "position_state",
        ):
            if field_name in data:
                self._seen_safety_fields.add(field_name)

    def _apply_sys_status(self, recv_ts_ms: int, payload: Any) -> None:
        self._last_sys_status_ts = recv_ts_ms
        if isinstance(payload, dict):
            sub_type = payload.get("sub_type")
            if sub_type is not None:
                self._sys_online = sub_type == 0

    def _apply_dock_events(self, recv_ts_ms: int, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        method = payload.get("method")
        if method == "flighttask_progress":
            self._last_flighttask_progress_ts = recv_ts_ms

    # ──────────────────────────────────────────────────────────────
    # phase / snapshot
    # ──────────────────────────────────────────────────────────────

    def _update_phase(self, recv_ts_ms: int) -> None:
        dock_osd_stale = (
            self._last_dock_osd_ts > 0
            and (recv_ts_ms - self._last_dock_osd_ts)
                > self.config.runtime.runtime.dock_osd_silence_to_offline_ms
        )
        if self._last_dock_osd_ts == 0:
            dock_osd_stale = True

        fs = self._dock_fields.get("flighttask_step_code")
        mc = self._drone_fields.get("mode_code")
        in_dock = self._dock_fields.get("drone_in_dock")
        height = self._drone_fields.get("height")
        vs = self._drone_fields.get("vertical_speed")

        res: PhaseResolution = resolve_phase(
            now_ms=recv_ts_ms,
            last_flighttask_progress_ts=self._last_flighttask_progress_ts,
            bare_flight_threshold_ms=self.config.runtime.runtime.bare_flight_threshold_ms,
            sys_online=self._sys_online,
            dock_osd_stale=dock_osd_stale,
            fs=fs,
            mc=mc,
            in_dock=in_dock,
            height=height,
            vs=vs,
            mode_code_map=self.config.mode_code_map,
        )

        if (
            res.phase != self._current_phase
            or res.phase_source != self._current_phase_source
        ):
            self._phase_transitions.append(
                PhaseTransition(
                    ts_ms=recv_ts_ms,
                    dock_sn=self.dock_sn,
                    phase_from=self._current_phase,
                    phase_to=res.phase,
                    phase_source_from=self._current_phase_source,
                    phase_source_to=res.phase_source,
                    reason=self._phase_transition_reason(res),
                    drone_height=height,
                    mode_code=mc,
                    drone_in_dock=in_dock,
                    warnings=res.warnings,
                )
            )
            self._current_phase = res.phase
            self._current_phase_source = res.phase_source

    def _phase_transition_reason(self, res: PhaseResolution) -> str:
        if res.warnings:
            return ",".join(res.warnings)
        if res.phase_source != self._current_phase_source:
            return f"source_change:{self._current_phase_source.value}->{res.phase_source.value}"
        return f"phase_change:{self._current_phase.value}->{res.phase.value}"

    def _snapshot_facts(self, recv_ts_ms: int) -> None:
        facts: dict[str, Any] = {
            F.PHASE: self._current_phase.value,
            F.PHASE_SOURCE: self._current_phase_source.value,
            F.DOCK_SN: self.dock_sn,
            F.DRONE_SN: self.drone_sn,
            F.SYS_ONLINE: self._sys_online,
            F.WARMING_UP: self.warming_up,
        }
        for key, fname in (
            ("cover_state", F.COVER_STATE),
            ("putter_state", F.PUTTER_STATE),
            ("emergency_stop_pressed", F.EMERGENCY_STOP_PRESSED),
            ("alarm_state", F.DOCK_ALARM_STATE),
            ("rainfall", F.RAINFALL),
            ("temperature", F.DOCK_INSIDE_TEMPERATURE),
            ("environment_temperature", F.ENVIRONMENT_TEMPERATURE),
            ("humidity", F.HUMIDITY),
            ("flighttask_step_code", F.FLIGHTTASK_STEP_CODE),
            ("drc_state", F.DRC_STATE),
            ("drone_in_dock", F.DRONE_IN_DOCK),
        ):
            if key in self._dock_fields:
                facts[fname] = self._dock_fields[key]
        ta = self._dock_fields.get("tilt_angle")
        if isinstance(ta, dict):
            facts[F.TILT_ANGLE_VALUE] = ta.get("value")
            facts[F.TILT_ANGLE_VALID] = ta.get("valid")
        sdr = self._dock_fields.get("sdr")
        if isinstance(sdr, dict):
            facts[F.SDR_UP_QUALITY] = sdr.get("up_quality")
            facts[F.SDR_DOWN_QUALITY] = sdr.get("down_quality")
        if "wind_speed" in self._dock_fields:
            facts[F.WIND_SPEED_DOCK] = self._dock_fields["wind_speed"]

        for key, fname in (
            ("mode_code", F.MODE_CODE),
            ("gear", F.GEAR),
            ("height", F.HEIGHT),
            ("vertical_speed", F.VERTICAL_SPEED),
            ("horizontal_speed", F.HORIZONTAL_SPEED),
            ("attitude_pitch", F.ATTITUDE_PITCH),
            ("attitude_roll", F.ATTITUDE_ROLL),
            ("attitude_head", F.ATTITUDE_HEAD),
            ("home_distance", F.HOME_DISTANCE),
            ("rth_altitude", F.RTH_ALTITUDE),
            ("wind_direction", F.WIND_DIRECTION),
            ("battery_capacity_percent", F.BATTERY_CAPACITY_PERCENT),
            ("battery_return_home_power", F.BATTERY_RETURN_HOME_POWER),
            ("battery_landing_power", F.BATTERY_LANDING_POWER),
            ("battery_remain_flight_time", F.BATTERY_REMAIN_FLIGHT_TIME),
            ("rtk_fixed", F.RTK_FIXED),
            ("rtk_is_fixed_code", F.RTK_IS_FIXED_CODE),
        ):
            if key in self._drone_fields:
                facts[fname] = self._drone_fields[key]
        if "wind_speed" in self._drone_fields:
            facts[F.WIND_SPEED_DRONE] = self._drone_fields["wind_speed"]

        gust = self._wind_gust_max_30s.max()
        if gust is not None:
            facts[F.WIND_GUST_MAX_30S] = gust

        self.facts_ring.append(freeze_facts(recv_ts_ms, facts))
