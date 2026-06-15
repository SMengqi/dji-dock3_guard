"""Stage 5-F Task 6: yaml + 跨架次 markdown 渲染单测."""

from __future__ import annotations

import yaml

from dock_guard.analytics.analyzers.battery_models import (
    BatteryReference,
    BucketStats,
    FlightAnomalyResult,
)
from dock_guard.analytics.analyzers.battery_report import (
    render_battery_markdown,
    render_battery_yaml,
)


def _good_ref() -> BatteryReference:
    return BatteryReference(
        buckets={
            "w0_3.h_lt50.soc_high": BucketStats(
                sample_count=412, mean=0.085, p50=0.082,
                p95=0.142, p99=0.198, max=0.245,
                residual_std=0.018, r_squared=0.74, status=None,
            ),
            "w6_inf.h_lt50.soc_low": BucketStats(
                sample_count=18, mean=0, p50=0, p95=0, p99=0, max=0,
                residual_std=0, r_squared=0, status="insufficient_data",
            ),
        },
        generated_at_ms=1718412345678,
        recording_count=100, total_sample_count=6243,
    )


class TestYaml:
    def test_schema_version_1(self) -> None:
        d = yaml.safe_load(render_battery_yaml(_good_ref()))
        assert d["schema_version"] == 1

    def test_yaml_buckets_populated(self) -> None:
        d = yaml.safe_load(render_battery_yaml(_good_ref()))
        assert len(d["buckets"]) == 2
        good = next(b for b in d["buckets"]
                    if b["bucket_key"] == "w0_3.h_lt50.soc_high")
        assert good["discharge_rate_pct_per_sec"]["mean"] == 0.085
        assert good["fit_quality"]["r_squared"] == 0.74

    def test_yaml_insufficient_data_bucket(self) -> None:
        d = yaml.safe_load(render_battery_yaml(_good_ref()))
        bad = next(b for b in d["buckets"]
                   if b["bucket_key"] == "w6_inf.h_lt50.soc_low")
        assert bad.get("status") == "insufficient_data"
        # 无 discharge_rate_pct_per_sec 字段
        assert "discharge_rate_pct_per_sec" not in bad


class TestMarkdown:
    def test_has_main_sections(self) -> None:
        md = render_battery_markdown(_good_ref(), [], skipped_v2_count=12)
        for sec in ("# 电池基线分析报告", "## 数据范围",
                    "## 桶占用情况", "## 异常架次清单", "## 拟合质量"):
            assert sec in md

    def test_shows_anomalies(self) -> None:
        anomalies = [FlightAnomalyResult(
            recording="rec_a", dock_sn="D", drone_sn="X",
            sample_count=40, red_count=5, yellow_count=2,
            is_anomaly=True, flags=[],
        )]
        md = render_battery_markdown(_good_ref(), anomalies)
        assert "rec_a" in md and "5" in md
