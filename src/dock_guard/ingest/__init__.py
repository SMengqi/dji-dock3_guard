"""数据接入层 (Phase 2+).

设计 §3:
- ReplaySource: 读 sim_dji_cloud_service 录制目录, 用于离线回放与 CI 基线
- MqttSource: aiomqtt 实时订阅 (Phase 7 实现)
两者实现同一 Source 协议, 下游管线共用.
"""

from dock_guard.ingest.mqtt_source import MqttSource, TlsSchemeMismatch
from dock_guard.ingest.replay_source import ReplaySource
from dock_guard.ingest.source import Envelope, Source, parse_topic

__all__ = [
    "Envelope",
    "MqttSource",
    "ReplaySource",
    "Source",
    "TlsSchemeMismatch",
    "parse_topic",
]
