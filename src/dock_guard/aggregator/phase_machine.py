"""飞行阶段机 (设计 §4.3)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from dock_guard.config import ModeCodeMapYaml
from dock_guard.types import (
    DroneInDock,
    FlightTaskStepCode,
    Phase,
    PhaseSource,
)


@dataclass(frozen=True, slots=True)
class PhaseResolution:
    phase: Phase
    phase_source: PhaseSource
    warnings: tuple[str, ...]


# §4.3.1 二维表
_PHASE_TABLE: Mapping[tuple[int, str], Phase] = {
    # fs=0 OPERATION_PREPARATION
    (0, "PREFLIGHT"): Phase.PREFLIGHT,
    (0, "TAKEOFF"):   Phase.PREFLIGHT,
    (0, "OFFLINE"):   Phase.OFFLINE,
    (0, "UPGRADING"): Phase.UPGRADING,
    (0, "IDLE"):      Phase.IDLE,

    # fs=1 IN_FLIGHT_OPERATION
    (1, "PREFLIGHT"): Phase.PREFLIGHT,
    (1, "TAKEOFF"):   Phase.TAKEOFF,
    (1, "CRUISE"):    Phase.CRUISE,
    (1, "AVOIDANCE"): Phase.AVOIDANCE,
    (1, "RTH"):       Phase.RTH,
    (1, "LANDING"):   Phase.LANDING,
    (1, "OFFLINE"):   Phase.OFFLINE,
    (1, "UPGRADING"): Phase.UPGRADING,
    (1, "IDLE"):      Phase.CRUISE,

    # fs=2 POST_OPERATION_RECOVERY
    (2, "PREFLIGHT"): Phase.POSTFLIGHT,
    (2, "TAKEOFF"):   Phase.POSTFLIGHT,
    (2, "CRUISE"):    Phase.POSTFLIGHT,
    (2, "AVOIDANCE"): Phase.POSTFLIGHT,
    (2, "RTH"):       Phase.POSTFLIGHT,
    (2, "LANDING"):   Phase.POSTFLIGHT,
    (2, "OFFLINE"):   Phase.OFFLINE,
    (2, "UPGRADING"): Phase.UPGRADING,
    (2, "IDLE"):      Phase.POSTFLIGHT,

    # fs=3 CUSTOM_FLIGHT_AREA_UPDATING
    (3, "PREFLIGHT"): Phase.IDLE,
    (3, "OFFLINE"):   Phase.OFFLINE,
    (3, "UPGRADING"): Phase.UPGRADING,
    (3, "IDLE"):      Phase.IDLE,

    # fs=4 TERRAIN_OBSTACLE_UPDATING
    (4, "PREFLIGHT"): Phase.IDLE,
    (4, "OFFLINE"):   Phase.OFFLINE,
    (4, "UPGRADING"): Phase.UPGRADING,
    (4, "IDLE"):      Phase.IDLE,

    # fs=5 MISSION_IDLE
    (5, "PREFLIGHT"): Phase.IDLE,
    (5, "OFFLINE"):   Phase.OFFLINE,
    (5, "UPGRADING"): Phase.UPGRADING,
    (5, "IDLE"):      Phase.IDLE,
}


def _bucket_name_for_mode_code(mc: int, mode_code_map: ModeCodeMapYaml) -> str | None:
    for bucket_name, codes in mode_code_map.phase_bucket.items():
        if mc in codes:
            return bucket_name
    return None


def derive_from_mode_code_bucket(bucket: str) -> Phase:
    return Phase(bucket)


def derive_from_mode_code(
    mc: int | None,
    *,
    in_dock: int | None,
    height: float | None,
    vs: float | None,
    mode_code_map: ModeCodeMapYaml,
) -> PhaseResolution:
    """§4.3.2 裸飞降级."""
    if mc is None:
        return PhaseResolution(Phase.OFFLINE, PhaseSource.FALLBACK_IDLE,
                               ("MODE_CODE_MISSING",))

    if mc == 14:  # NOT_CONNECTED
        return PhaseResolution(Phase.OFFLINE, PhaseSource.MODE_CODE, ())

    if mc == 16:  # VIRTUAL_STICK
        if height is not None and abs(height) < 0.5 and (vs is None or abs(vs) < 0.5):
            return PhaseResolution(Phase.IDLE, PhaseSource.MODE_CODE, ())
        return PhaseResolution(Phase.CRUISE, PhaseSource.MODE_CODE, ())

    bucket = _bucket_name_for_mode_code(mc, mode_code_map)
    if bucket is None:
        # 未知 mc -> WARN_AND_TREAT_AS_AIRBORNE (§4.4)
        return PhaseResolution(Phase.CRUISE, PhaseSource.MODE_CODE, ("UNKNOWN_MODE_CODE",))

    return PhaseResolution(
        derive_from_mode_code_bucket(bucket),
        PhaseSource.MODE_CODE,
        (),
    )


def derive_from_dock_task(
    fs: int | None,
    mc: int | None,
    *,
    in_dock: int | None,
    height: float | None,
    vs: float | None,
    mode_code_map: ModeCodeMapYaml,
) -> PhaseResolution:
    """§4.3.1 二维表."""
    if fs is None:
        return derive_from_mode_code(
            mc, in_dock=in_dock, height=height, vs=vs, mode_code_map=mode_code_map
        )

    # fs=255 AIRCRAFT_ABNORMAL
    if fs == FlightTaskStepCode.AIRCRAFT_ABNORMAL.value:
        res = derive_from_mode_code(
            mc, in_dock=in_dock, height=height, vs=vs, mode_code_map=mode_code_map
        )
        return PhaseResolution(
            res.phase,
            PhaseSource.FLIGHTTASK_STEP_CODE,
            ("AIRCRAFT_ABNORMAL_FLAG", *res.warnings),
        )

    mc_bucket = _bucket_name_for_mode_code(mc, mode_code_map) if mc is not None else None

    if mc_bucket is None:
        # mc 未知, 靠 fs 推断
        if fs == FlightTaskStepCode.POST_OPERATION_RECOVERY.value:
            return PhaseResolution(Phase.POSTFLIGHT, PhaseSource.FLIGHTTASK_STEP_CODE, ())
        if fs in (
            FlightTaskStepCode.CUSTOM_FLIGHT_AREA_UPDATING.value,
            FlightTaskStepCode.TERRAIN_OBSTACLE_UPDATING.value,
            FlightTaskStepCode.MISSION_IDLE.value,
        ):
            return PhaseResolution(Phase.IDLE, PhaseSource.FLIGHTTASK_STEP_CODE, ())
        return PhaseResolution(
            Phase.CRUISE,
            PhaseSource.FLIGHTTASK_STEP_CODE,
            ("UNKNOWN_MODE_CODE",),
        )

    phase = _PHASE_TABLE.get((fs, mc_bucket))
    if phase is None:
        # 异常组合 -> mc 桶兜底 + 标记
        return PhaseResolution(
            derive_from_mode_code_bucket(mc_bucket),
            PhaseSource.FLIGHTTASK_STEP_CODE,
            ("UNEXPECTED_PHASE_COMBO",),
        )

    return PhaseResolution(phase, PhaseSource.FLIGHTTASK_STEP_CODE, ())


def resolve_phase(
    *,
    now_ms: int,
    last_flighttask_progress_ts: int,
    bare_flight_threshold_ms: int,
    sys_online: bool,
    dock_osd_stale: bool,
    fs: int | None,
    mc: int | None,
    in_dock: int | None,
    height: float | None,
    vs: float | None,
    mode_code_map: ModeCodeMapYaml,
) -> PhaseResolution:
    """顶层调度 (设计 §4.3 resolve_phase 伪代码)."""
    if not sys_online or dock_osd_stale:
        return PhaseResolution(Phase.OFFLINE, PhaseSource.FALLBACK_IDLE, ())

    dock_task_age_ms = now_ms - last_flighttask_progress_ts

    if dock_task_age_ms <= bare_flight_threshold_ms and last_flighttask_progress_ts > 0:
        return derive_from_dock_task(
            fs, mc, in_dock=in_dock, height=height, vs=vs, mode_code_map=mode_code_map
        )

    airborne_set = set(mode_code_map.airborne_set)
    drone_airborne = (mc is not None and mc in airborne_set) or (
        in_dock == DroneInDock.OUTSIDE.value and (height or 0) > 1.0
    )
    if drone_airborne:
        return derive_from_mode_code(
            mc, in_dock=in_dock, height=height, vs=vs, mode_code_map=mode_code_map
        )

    return PhaseResolution(Phase.IDLE, PhaseSource.FALLBACK_IDLE, ())
