"""Stage 4-E: 离线分析子系统骨架 (设计 §13).

入口: python -m dock_guard.analytics <recording_dir>
单录制 -> 1 份 report.json + report.md; 父目录 -> N 份 + index.md.
"""

from dock_guard.analytics.collector import collect
from dock_guard.analytics.models import SCHEMA_VERSION, FlightMetrics, FlightReport

__all__ = ["SCHEMA_VERSION", "FlightMetrics", "FlightReport", "collect"]
