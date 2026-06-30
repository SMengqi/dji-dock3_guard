"""BatterySample 速度字段单测 (纯添加, 默认 None, 向后兼容老 dict)."""

from __future__ import annotations

from dataclasses import asdict

from dock_guard.analytics.models import BatterySample


def test_speed_fields_default_none() -> None:
    s = BatterySample(rel_ms=0, percent=80, height_m=10.0, wind_ms=2.0)
    assert s.horizontal_speed_ms is None
    assert s.vertical_speed_ms is None


def test_speed_fields_roundtrip_asdict() -> None:
    s = BatterySample(
        rel_ms=0, percent=80, height_m=10.0, wind_ms=2.0,
        horizontal_speed_ms=8.5, vertical_speed_ms=-1.2,
    )
    d = asdict(s)
    assert d["horizontal_speed_ms"] == 8.5
    assert d["vertical_speed_ms"] == -1.2


def test_old_sample_dict_without_speed_loads() -> None:
    """老 v3 report.json 的样本 dict 无速度字段 -> BatterySample(**s) 默认填 None."""
    old = {
        "rel_ms": 0, "percent": 80, "height_m": 10.0,
        "wind_ms": 2.0, "wind_direction": None,
    }
    s = BatterySample(**old)
    assert s.horizontal_speed_ms is None
    assert s.vertical_speed_ms is None
