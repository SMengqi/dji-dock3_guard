"""dock_guard — DJI Dock 3 飞行安全告警系统 (v2).

设计原则:
- 纯告警系统, 不向 DJI 设备下发任何指令.
- 对 broker 只 SUBSCRIBE, 永不 PUBLISH 到 thing/+/services.
- 不写原始 envelope, 由 sim_dji_cloud_service 负责采集.
"""

__version__ = "0.2.0"
