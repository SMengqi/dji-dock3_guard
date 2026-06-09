"""Phase 3 单元测试: phase_machine 二维表 + 裸飞降级 (设计 §4.3)."""

from __future__ import annotations

import pathlib

import pytest

from dock_guard.aggregator.phase_machine import (
    derive_from_dock_task,
    derive_from_mode_code,
    resolve_phase,
)
from dock_guard.config import ModeCodeMapYaml, load_mode_code_map
from dock_guard.types import Phase, PhaseSource


@pytest.fixture(scope="module")
def mc_map() -> ModeCodeMapYaml:
    p = pathlib.Path(__file__).resolve().parents[2] / "config" / "mode_code_map.yaml"
    return load_mode_code_map(p)


class TestDeriveFromDockTask:
    def test_fs0_preflight_to_preflight(self, mc_map: ModeCodeMapYaml) -> None:
        r = derive_from_dock_task(0, 0, in_dock=1, height=0, vs=0, mode_code_map=mc_map)
        assert r.phase == Phase.PREFLIGHT
        assert r.phase_source == PhaseSource.FLIGHTTASK_STEP_CODE
        assert r.warnings == ()

    def test_fs0_takeoff_transition_tick(self, mc_map: ModeCodeMapYaml) -> None:
        r = derive_from_dock_task(0, 4, in_dock=0, height=2, vs=2, mode_code_map=mc_map)
        assert r.phase == Phase.PREFLIGHT

    def test_fs1_cruise(self, mc_map: ModeCodeMapYaml) -> None:
        r = derive_from_dock_task(1, 5, in_dock=0, height=50, vs=0, mode_code_map=mc_map)
        assert r.phase == Phase.CRUISE

    def test_fs1_rth(self, mc_map: ModeCodeMapYaml) -> None:
        r = derive_from_dock_task(1, 9, in_dock=0, height=80, vs=0, mode_code_map=mc_map)
        assert r.phase == Phase.RTH

    def test_fs1_landing(self, mc_map: ModeCodeMapYaml) -> None:
        r = derive_from_dock_task(1, 10, in_dock=0, height=5, vs=-1, mode_code_map=mc_map)
        assert r.phase == Phase.LANDING

    def test_fs2_postflight_any_mc(self, mc_map: ModeCodeMapYaml) -> None:
        r = derive_from_dock_task(2, 5, in_dock=1, height=0, vs=0, mode_code_map=mc_map)
        assert r.phase == Phase.POSTFLIGHT

    def test_fs5_mission_idle(self, mc_map: ModeCodeMapYaml) -> None:
        r = derive_from_dock_task(5, 0, in_dock=1, height=0, vs=0, mode_code_map=mc_map)
        assert r.phase == Phase.IDLE

    def test_fs255_aircraft_abnormal_flag(self, mc_map: ModeCodeMapYaml) -> None:
        r = derive_from_dock_task(255, 5, in_dock=0, height=50, vs=0, mode_code_map=mc_map)
        assert r.phase == Phase.CRUISE
        assert "AIRCRAFT_ABNORMAL_FLAG" in r.warnings

    def test_unexpected_combo_falls_back(self, mc_map: ModeCodeMapYaml) -> None:
        r = derive_from_dock_task(0, 5, in_dock=0, height=50, vs=0, mode_code_map=mc_map)
        assert r.phase == Phase.CRUISE
        assert "UNEXPECTED_PHASE_COMBO" in r.warnings


class TestDeriveFromModeCode:
    def test_mc_14_offline(self, mc_map: ModeCodeMapYaml) -> None:
        r = derive_from_mode_code(14, in_dock=0, height=None, vs=None, mode_code_map=mc_map)
        assert r.phase == Phase.OFFLINE
        assert r.phase_source == PhaseSource.MODE_CODE

    def test_mc_16_low_height_idle(self, mc_map: ModeCodeMapYaml) -> None:
        r = derive_from_mode_code(16, in_dock=1, height=0.1, vs=0.0, mode_code_map=mc_map)
        assert r.phase == Phase.IDLE

    def test_mc_16_airborne_cruise(self, mc_map: ModeCodeMapYaml) -> None:
        r = derive_from_mode_code(16, in_dock=0, height=20, vs=0, mode_code_map=mc_map)
        assert r.phase == Phase.CRUISE

    def test_mc_5_wayline(self, mc_map: ModeCodeMapYaml) -> None:
        r = derive_from_mode_code(5, in_dock=0, height=50, vs=0, mode_code_map=mc_map)
        assert r.phase == Phase.CRUISE

    def test_unknown_mc_treated_as_airborne(self, mc_map: ModeCodeMapYaml) -> None:
        r = derive_from_mode_code(99, in_dock=0, height=50, vs=0, mode_code_map=mc_map)
        assert r.phase == Phase.CRUISE
        assert "UNKNOWN_MODE_CODE" in r.warnings

    def test_none_mc(self, mc_map: ModeCodeMapYaml) -> None:
        r = derive_from_mode_code(None, in_dock=None, height=None, vs=None,
                                  mode_code_map=mc_map)
        assert r.phase == Phase.OFFLINE
        assert "MODE_CODE_MISSING" in r.warnings


class TestResolvePhase:
    def test_offline_when_sys_offline(self, mc_map: ModeCodeMapYaml) -> None:
        r = resolve_phase(
            now_ms=10000, last_flighttask_progress_ts=9000,
            bare_flight_threshold_ms=5000,
            sys_online=False, dock_osd_stale=False,
            fs=1, mc=5, in_dock=0, height=50, vs=0,
            mode_code_map=mc_map,
        )
        assert r.phase == Phase.OFFLINE
        assert r.phase_source == PhaseSource.FALLBACK_IDLE

    def test_offline_when_dock_osd_stale(self, mc_map: ModeCodeMapYaml) -> None:
        r = resolve_phase(
            now_ms=10000, last_flighttask_progress_ts=9000,
            bare_flight_threshold_ms=5000,
            sys_online=True, dock_osd_stale=True,
            fs=1, mc=5, in_dock=0, height=50, vs=0,
            mode_code_map=mc_map,
        )
        assert r.phase == Phase.OFFLINE

    def test_fresh_dock_task_uses_table(self, mc_map: ModeCodeMapYaml) -> None:
        r = resolve_phase(
            now_ms=10000, last_flighttask_progress_ts=9000,
            bare_flight_threshold_ms=5000,
            sys_online=True, dock_osd_stale=False,
            fs=1, mc=5, in_dock=0, height=50, vs=0,
            mode_code_map=mc_map,
        )
        assert r.phase == Phase.CRUISE
        assert r.phase_source == PhaseSource.FLIGHTTASK_STEP_CODE

    def test_stale_dock_task_airborne_drone_bare_flight(self, mc_map: ModeCodeMapYaml) -> None:
        r = resolve_phase(
            now_ms=20000, last_flighttask_progress_ts=10000,
            bare_flight_threshold_ms=5000,
            sys_online=True, dock_osd_stale=False,
            fs=1, mc=5, in_dock=0, height=50, vs=0,
            mode_code_map=mc_map,
        )
        assert r.phase == Phase.CRUISE
        assert r.phase_source == PhaseSource.MODE_CODE

    def test_stale_dock_task_drone_on_ground_fallback_idle(self, mc_map: ModeCodeMapYaml) -> None:
        r = resolve_phase(
            now_ms=20000, last_flighttask_progress_ts=10000,
            bare_flight_threshold_ms=5000,
            sys_online=True, dock_osd_stale=False,
            fs=0, mc=0, in_dock=1, height=0, vs=0,
            mode_code_map=mc_map,
        )
        assert r.phase == Phase.IDLE
        assert r.phase_source == PhaseSource.FALLBACK_IDLE
