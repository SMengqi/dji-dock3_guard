"""Stage 5-F: 电池分析流程编排 + CLI 入口 (设计 §4.1 + §9).

库函数: load_v3_reports / build_reference / evaluate_all_flights
CLI 入口: python -m dock_guard.analytics.analyzers.battery <父目录>

用法 (CLI):
    python -m dock_guard.analytics.analyzers.battery <父目录>
    python -m dock_guard.analytics.analyzers.battery <父目录> --out <dir>
    python -m dock_guard.analytics.analyzers.battery <父目录> --min-samples 30
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import traceback
from pathlib import Path
from typing import Any

from dock_guard.analytics.analyzers.battery_anomaly import evaluate_flight
from dock_guard.analytics.analyzers.battery_buckets import (
    compute_discharge_rates,
    group_rates_by_bucket,
    smooth_30s,
)
from dock_guard.analytics.analyzers.battery_fit import compute_bucket_stats
from dock_guard.analytics.analyzers.battery_models import (
    BatteryReference,
    BucketStats,
    FlightAnomalyResult,
)
from dock_guard.analytics.analyzers.battery_report import (
    render_battery_markdown,
    render_battery_yaml,
)
from dock_guard.analytics.models import BatterySample


def load_v3_reports(parent: pathlib.Path) -> tuple[list[dict[str, Any]], int]:
    """读父目录下所有 v3 report.json. 返 (reports, skipped_v2_count)."""
    reports: list[dict[str, Any]] = []
    skipped_v2 = 0
    for sub in sorted(p for p in parent.iterdir() if p.is_dir()):
        rep_path = sub / "dock_guard_report" / "report.json"
        if not rep_path.exists():
            continue
        try:
            d = json.loads(rep_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("schema_version") not in (3, 4):
            skipped_v2 += 1
            continue
        reports.append(d)
    return reports, skipped_v2


def build_reference(
    reports: list[dict[str, Any]], *, min_samples: int = 30,
) -> tuple[BatteryReference, int]:
    """聚合 N 报告 -> BatteryReference. 返 (ref, total_sample_count)."""
    all_groups: dict[str, list[float]] = {}
    total = 0
    for d in reports:
        samples = [BatterySample(**s) for s in d.get("battery_samples", [])]
        total += len(samples)
        rates = compute_discharge_rates(samples)
        smoothed = smooth_30s(rates)
        # smoothed[i] 对应 samples[i+1] 的速率
        groups = group_rates_by_bucket(samples[1:], smoothed)
        for key, rs in groups.items():
            all_groups.setdefault(key, []).extend(rs)

    buckets: dict[str, BucketStats] = {}
    for key, rates in all_groups.items():
        stats = compute_bucket_stats(rates, min_samples=min_samples)
        if stats is None:
            buckets[key] = BucketStats(
                sample_count=len(rates),
                mean=0, p50=0, p95=0, p99=0, max=0,
                residual_std=0, r_squared=0,
                status="insufficient_data",
            )
        else:
            d_rate = stats["discharge_rate_pct_per_sec"]
            fit = stats["fit_quality"]
            buckets[key] = BucketStats(
                sample_count=stats["sample_count"],
                mean=d_rate["mean"], p50=d_rate["p50"],
                p95=d_rate["p95"], p99=d_rate["p99"], max=d_rate["max"],
                residual_std=fit["residual_std"], r_squared=fit["r_squared"],
                status=None,
            )
    return BatteryReference(
        buckets=buckets,
        recording_count=len(reports),
        total_sample_count=total,
    ), total


def evaluate_all_flights(
    reports: list[dict[str, Any]], ref: BatteryReference,
) -> list[FlightAnomalyResult]:
    """对每架次评分."""
    out: list[FlightAnomalyResult] = []
    for d in reports:
        samples = [BatterySample(**s) for s in d.get("battery_samples", [])]
        if not samples:
            continue
        out.append(evaluate_flight(
            samples, ref,
            recording=d.get("recording", "?"),
            dock_sn=d.get("dock_sn", "?"),
            drone_sn=d.get("drone_sn"),
        ))
    return out


# ─── CLI 入口 ──────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dock_guard.analytics.analyzers.battery",
        description="电池基线分析: 父目录 v3 report.json -> "
                    "battery_reference.yaml + report.md",
    )
    p.add_argument("path", type=Path, help="父目录 (含 N 个已分析录制子目录)")
    p.add_argument("--out", type=Path, default=None,
                   help="输出目录 (默认 <path>/battery_analysis/)")
    p.add_argument("--min-samples", type=int, default=30,
                   help="桶内最小样本数 (< 标 insufficient_data, 默认 30)")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--config-dir", type=Path, default=None,
                   help="(暂未使用, 占位为未来扩展)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = args.path.resolve()
    if not path.exists() or not path.is_dir():
        print(f"路径不存在或非目录: {path}", file=sys.stderr)
        return 2

    if not args.quiet:
        print(f"loading reports from {path} ...")
    reports, skipped_v2 = load_v3_reports(path)
    if not reports:
        print(f"父目录无 v3 report.json (先跑 Stage 4-E): {path}", file=sys.stderr)
        return 2

    if not args.quiet:
        print(f"loaded {len(reports)} v3 reports, skipped {skipped_v2} v2 reports")

    try:
        ref, total_samples = build_reference(reports, min_samples=args.min_samples)
        if not args.quiet:
            print(f"  -> {len(ref.buckets)} buckets, {total_samples} samples")
        anomalies = evaluate_all_flights(reports, ref)
        n_anom = sum(1 for a in anomalies if a.is_anomaly)
        if not args.quiet:
            print(f"  -> {n_anom} / {len(anomalies)} anomalous flights")

        out_dir = (args.out if args.out is not None
                   else path / "battery_analysis").resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "battery_reference.yaml").write_text(
            render_battery_yaml(ref), encoding="utf-8")
        (out_dir / "report.md").write_text(
            render_battery_markdown(ref, anomalies, skipped_v2_count=skipped_v2),
            encoding="utf-8")
        if not args.quiet:
            print(f"output: {out_dir}")
    except Exception as e:
        traceback.print_exc()
        print(f"failed: {e}", file=sys.stderr)
        return 1

    return 1 if skipped_v2 > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
