"""FrozenFacts + fact 命名常量 (设计 §5.2.1)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True, slots=True)
class FrozenFacts:
    """单帧 fact 快照, 不可变."""

    recv_ts_ms: int
    facts: Mapping[str, Any]


def freeze_facts(recv_ts_ms: int, facts: dict[str, Any]) -> FrozenFacts:
    """构造 FrozenFacts. facts 做浅拷贝再用 MappingProxyType 包装."""
    snapshot = dict(facts)
    return FrozenFacts(recv_ts_ms=recv_ts_ms, facts=MappingProxyType(snapshot))


class F:
    """规则可见的 fact 名常量 (设计 §5.2 Phase 3 子集)."""

    # 元信息
    PHASE = "phase"
    PHASE_SOURCE = "phase_source"
    DOCK_SN = "dock_sn"
    DRONE_SN = "drone_sn"
    SYS_ONLINE = "sys_online"
    WARMING_UP = "warming_up"

    # 飞行器姿态/动力学
    MODE_CODE = "mode_code"
    GEAR = "gear"
    HEIGHT = "height"
    ELEVATION = "elevation"
    VERTICAL_SPEED = "vertical_speed"
    HORIZONTAL_SPEED = "horizontal_speed"
    ATTITUDE_PITCH = "attitude_pitch"
    ATTITUDE_ROLL = "attitude_roll"
    ATTITUDE_HEAD = "attitude_head"
    HOME_DISTANCE = "home_distance"
    RTH_ALTITUDE = "rth_altitude"

    # 电池 (飞行器)
    BATTERY_CAPACITY_PERCENT = "battery_capacity_percent"
    BATTERY_RETURN_HOME_POWER = "battery_return_home_power"
    BATTERY_LANDING_POWER = "battery_landing_power"
    BATTERY_REMAIN_FLIGHT_TIME = "battery_remain_flight_time"

    # 定位
    RTK_FIXED = "rtk_fixed"
    RTK_IS_FIXED_CODE = "rtk_is_fixed_code"
    GPS_NUMBER = "gps_number"
    RTK_NUMBER = "rtk_number"

    # 风
    WIND_SPEED_DRONE = "wind_speed_drone"
    WIND_SPEED_DOCK = "wind_speed_dock"
    WIND_DIRECTION = "wind_direction"
    WIND_GUST_MAX_30S = "wind_gust_max_30s"

    # 环境
    RAINFALL = "rainfall"
    DOCK_INSIDE_TEMPERATURE = "dock_inside_temperature"
    ENVIRONMENT_TEMPERATURE = "environment_temperature"
    HUMIDITY = "humidity"

    # 机场本体
    COVER_STATE = "cover_state"
    PUTTER_STATE = "putter_state"
    EMERGENCY_STOP_PRESSED = "emergency_stop_pressed"
    DOCK_ALARM_STATE = "dock_alarm_state"
    TILT_ANGLE_VALUE = "tilt_angle_value"
    TILT_ANGLE_VALID = "tilt_angle_valid"
    DRONE_IN_DOCK = "drone_in_dock"

    # 任务步进
    FLIGHTTASK_STEP_CODE = "flighttask_step_code"
    DRC_STATE = "drc_state"

    # 链路
    SDR_UP_QUALITY = "sdr_up_quality"
    SDR_DOWN_QUALITY = "sdr_down_quality"
