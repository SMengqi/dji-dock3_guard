"""全局类型与枚举.

设计原则:
- 所有 enum 值与 DJI Cloud API 官方文档严格对齐 (§3.2).
- 字段名/取值在 v2 已锁定, 后续 phase 不应再改.
- IntEnum 用于 enum_int 类型 (DJI 官方 schema);
  StrEnum 用于 enum_str 与内部状态.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum

# ─── 告警分级 (§5.4) ─────────────────────────────────────────────────


class Severity(IntEnum):
    """告警级别. 数值越大越严重, 排序见 §5.4."""

    INFO = 1
    WARN = 2
    RETURN = 3
    BLOCK = 4
    EMERGENCY = 5


# ─── 飞行阶段 (§4.0) ────────────────────────────────────────────────


class Phase(StrEnum):
    """canonical 10 档飞行阶段."""

    OFFLINE = "OFFLINE"
    IDLE = "IDLE"
    PREFLIGHT = "PREFLIGHT"
    TAKEOFF = "TAKEOFF"
    CRUISE = "CRUISE"
    AVOIDANCE = "AVOIDANCE"
    RTH = "RTH"
    LANDING = "LANDING"
    POSTFLIGHT = "POSTFLIGHT"
    UPGRADING = "UPGRADING"


class PhaseSource(StrEnum):
    """phase 的真值来源 (§4.0). 取代 v1 BARE_FLIGHT 概念."""

    FLIGHTTASK_STEP_CODE = "flighttask_step_code"
    MODE_CODE = "mode_code"
    FALLBACK_IDLE = "fallback_idle"


# ─── 告警通道 (§6.2 / §7) ────────────────────────────────────────────


class ChannelKind(StrEnum):
    PANEL = "panel"
    WEBHOOK = "webhook"
    DINGTALK = "dingtalk"


# ─── DJI 字段枚举 (§3.2 官方表) ──────────────────────────────────────


class DroneModeCode(IntEnum):
    """飞行器 mode_code: 22 档 (官方 21 + CN 文档新增 21)."""

    STANDBY = 0
    TAKEOFF_PREPARATION = 1
    TAKEOFF_PREPARATION_COMPLETED = 2
    MANUAL_FLIGHT = 3
    AUTOMATIC_TAKEOFF = 4
    WAYLINE_FLIGHT = 5
    PANORAMIC_PHOTOGRAPHY = 6
    INTELLIGENT_TRACKING = 7
    ADS_B_AVOIDANCE = 8
    AUTO_RTH = 9
    AUTO_LANDING = 10
    FORCED_LANDING = 11
    THREE_BLADE_LANDING = 12
    UPGRADING = 13
    NOT_CONNECTED = 14
    APAS = 15
    VIRTUAL_STICK = 16
    LIVE_FLIGHT_CONTROLS = 17
    AIRBORNE_RTK_FIXING = 18
    DOCK_ADDRESS_SELECTING = 19
    POI = 20
    FAR_FROM_DOCK_WAYLINE = 21


class DockModeCode(IntEnum):
    """Dock 3 mode_code: 6 档."""

    IDLE = 0
    ON_SITE_DEBUG = 1
    REMOTE_DEBUG = 2
    FIRMWARE_UPGRADE = 3
    IN_OPERATION = 4
    TO_BE_CALIBRATED = 5


class Rainfall(IntEnum):
    NONE = 0
    LIGHT = 1
    MODERATE = 2
    HEAVY = 3


class CoverState(IntEnum):
    """cover_state (即原'舱门状态'): 4 档."""

    DISABLE = 0
    ON = 1
    HALF_OPEN = 2
    ABNORMAL = 3


class PutterState(IntEnum):
    """推杆状态: 4 档, 同 CoverState."""

    DISABLE = 0
    ON = 1
    HALF_OPEN = 2
    ABNORMAL = 3


class RtkFixedCode(IntEnum):
    """position_state.is_fixed: 4 档."""

    NOT_STARTED = 0
    FIXING = 1
    FIXING_SUCCESSFUL = 2  # 这一档 = rtk_fixed = True
    FIXING_FAILED = 3


class WindDirection(IntEnum):
    """风向: 8 方位 (非连续角度)."""

    TRUE_NORTH = 1
    NORTHEAST = 2
    EAST = 3
    SOUTHEAST = 4
    SOUTH = 5
    SOUTHWEST = 6
    WEST = 7
    NORTHWEST = 8


class FlightTaskStepCode(IntEnum):
    """dock 端任务步进真值 (§3.2.2)."""

    OPERATION_PREPARATION = 0
    IN_FLIGHT_OPERATION = 1
    POST_OPERATION_RECOVERY = 2
    CUSTOM_FLIGHT_AREA_UPDATING = 3
    TERRAIN_OBSTACLE_UPDATING = 4
    MISSION_IDLE = 5
    AIRCRAFT_ABNORMAL = 255


class DrcState(IntEnum):
    NOT_CONNECTED = 0
    CONNECTING = 1
    CONNECTED = 2


class DroneInDock(IntEnum):
    OUTSIDE = 0
    INSIDE = 1


class EmergencyStopState(IntEnum):
    DISABLE = 0
    ENABLE = 1  # 急停按钮已按下


# ─── MQTT topic 配置 key (§15.1.1) ──────────────────────────────────


class TopicKey(StrEnum):
    """runtime.yaml topic_defaults 配置 key.

    设计 §15.1.1: 14 个 topic 全列, key 名 → MQTT topic 模板由代码维护.
    """

    DOCK_OSD = "dock_osd"
    DOCK_STATE = "dock_state"
    DOCK_EVENTS = "dock_events"
    DOCK_REQUESTS = "dock_requests"
    DOCK_REQUESTS_REPLY = "dock_requests_reply"
    DOCK_SERVICES_REPLY = "dock_services_reply"
    DOCK_SYS_STATUS = "dock_sys_status"
    DRONE_OSD = "drone_osd"
    DRONE_STATE = "drone_state"
    DRONE_STATE_REPLY = "drone_state_reply"
    DRONE_EVENTS = "drone_events"
    DOCK_DRC_UP = "dock_drc_up"
    DOCK_DRC_DOWN = "dock_drc_down"
    DOCK_SERVICES = "dock_services"


TOPIC_TEMPLATES: dict[TopicKey, str] = {
    TopicKey.DOCK_OSD: "thing/product/{dock_sn}/osd",
    TopicKey.DOCK_STATE: "thing/product/{dock_sn}/state",
    TopicKey.DOCK_EVENTS: "thing/product/{dock_sn}/events",
    TopicKey.DOCK_REQUESTS: "thing/product/{dock_sn}/requests",
    TopicKey.DOCK_REQUESTS_REPLY: "thing/product/{dock_sn}/requests_reply",
    TopicKey.DOCK_SERVICES_REPLY: "thing/product/{dock_sn}/services_reply",
    TopicKey.DOCK_SYS_STATUS: "sys/product/{dock_sn}/status",
    TopicKey.DRONE_OSD: "thing/product/{drone_sn}/osd",
    TopicKey.DRONE_STATE: "thing/product/{drone_sn}/state",
    TopicKey.DRONE_STATE_REPLY: "thing/product/{drone_sn}/state_reply",
    TopicKey.DRONE_EVENTS: "thing/product/{drone_sn}/events",
    TopicKey.DOCK_DRC_UP: "thing/product/{dock_sn}/drc/up",
    TopicKey.DOCK_DRC_DOWN: "thing/product/{dock_sn}/drc/down",
    TopicKey.DOCK_SERVICES: "thing/product/{dock_sn}/services",
}

# 需要 drone_sn 才能展开的 topic_key (drone OSD 首帧到达前无法订阅).
DRONE_SN_TOPICS: frozenset[TopicKey] = frozenset(
    {
        TopicKey.DRONE_OSD,
        TopicKey.DRONE_STATE,
        TopicKey.DRONE_STATE_REPLY,
        TopicKey.DRONE_EVENTS,
    }
)
