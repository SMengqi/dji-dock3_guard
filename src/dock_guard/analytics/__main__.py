"""Stage 4-E: 离线分析 CLI 入口.

谁调用: python -m dock_guard.analytics; tests/unit/test_analytics_cli.py.
同义文件: 无. 数据: 读 manifest+yaml, 写 report.json+md+index.md.
用户指令: "继续 T3".

用法:
    python -m dock_guard.analytics <recording_dir>
    python -m dock_guard.analytics <parent_dir>           # batch
    python -m dock_guard.analytics <dir> --out /tmp/reports
    python -m dock_guard.analytics <dir> --force
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from dock_guard.analytics.collector import collect
from dock_guard.analytics.models import FlightMetrics, FlightReport
from dock_guard.analytics.report import (
    render_index_md,
    render_json,
    render_markdown,
)


def _resolve_config_dir(user_arg: Path | None) -> Path:
    if user_arg is not None:
        return user_arg.resolve()
    for cand in (Path("/app/config"), Path("./config")):
        if cand.exists():
            return cand.resolve()
    return Path("./config").resolve()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dock_guard.analytics",
        description="离线复盘: 录制目录 -> report.json + report.md (+ 批量 index.md).",
    )
    p.add_argument("path", type=Path,
                   help="录制目录 (含 manifest.json) 或父目录 (含多个 recording 子目录)")
    p.add_argument("--out", type=Path, default=None,
                   help="输出目录 (默认就地写到 <recording>/dock_guard_report/)")
    p.add_argument("--force", action="store_true",
                   help="重跑已分析的 (默认跳过)")
    p.add_argument("--quiet", action="store_true", help="不打进度心跳")
    p.add_argument("--config-dir", type=Path, default=None,
                   help="配置目录 (默认 /app/config 或 ./config)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = args.path.resolve()
    if not path.exists():
        print(f"路径不存在: {path}", file=sys.stderr)
        return 2

    config_dir = _resolve_config_dir(args.config_dir)
    if not (config_dir / "mode_code_map.yaml").exists():
        print(f"config 目录缺关键 yaml: {config_dir}", file=sys.stderr)
        return 2

    if (path / "manifest.json").exists():
        return _process_single(path, args.out, args.force, args.quiet, config_dir)
    return _process_batch(path, args.out, args.force, args.quiet, config_dir)


def _output_dir_for(rec_dir: Path, override_out: Path | None) -> Path:
    if override_out is None:
        return rec_dir / "dock_guard_report"
    return override_out / rec_dir.name


def _write_report(rep: FlightReport, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(render_json(rep), encoding="utf-8")
    (out_dir / "report.md").write_text(render_markdown(rep), encoding="utf-8")


def _process_single(
    rec_dir: Path, override_out: Path | None, force: bool,
    quiet: bool, config_dir: Path,
) -> int:
    out_dir = _output_dir_for(rec_dir, override_out)
    if (out_dir / "report.json").exists() and not force:
        if not quiet:
            print(f"skip (already analyzed): {rec_dir.name}")
        return 0
    try:
        rep = collect(rec_dir, config_dir)
        _write_report(rep, out_dir)
        if not quiet:
            print(f"ok: {rec_dir.name} -> {out_dir}")
        return 0
    except Exception as e:
        traceback.print_exc()
        print(f"failed: {rec_dir.name}: {e}", file=sys.stderr)
        return 1


def _process_batch(
    parent: Path, override_out: Path | None, force: bool,
    quiet: bool, config_dir: Path,
) -> int:
    subdirs = sorted(d for d in parent.iterdir()
                     if d.is_dir() and d.name != "dock_guard_report")
    if not subdirs:
        print(f"父目录无 recording 子目录: {parent}", file=sys.stderr)
        return 2

    rows: list[tuple[str, FlightReport | None, str | None]] = []
    any_failed = False
    n_total = len(subdirs)
    for i, sub in enumerate(subdirs, 1):
        if not (sub / "manifest.json").exists():
            if not quiet:
                print(f"[{i}/{n_total}] skip (no manifest): {sub.name}")
            continue
        out_dir = _output_dir_for(sub, override_out)
        if (out_dir / "report.json").exists() and not force:
            if not quiet:
                print(f"[{i}/{n_total}] skip (analyzed): {sub.name}")
            try:
                d = json.loads((out_dir / "report.json").read_text())
                rows.append((sub.name, _from_dict(d), None))
            except Exception as e:
                rows.append((sub.name, None, f"已有 report.json 解析失败: {e}"))
                any_failed = True
            continue
        # 验 manifest 可读, 否则当损坏
        try:
            json.loads((sub / "manifest.json").read_text())
        except Exception as e:
            rows.append((sub.name, None, f"manifest.json 解析失败: {e}"))
            any_failed = True
            if not quiet:
                print(f"[{i}/{n_total}] corrupt manifest: {sub.name}", file=sys.stderr)
            continue
        if not quiet:
            print(f"[{i}/{n_total}] processing: {sub.name}")
        try:
            rep = collect(sub, config_dir)
            _write_report(rep, out_dir)
            rows.append((sub.name, rep, None))
        except Exception as e:
            rows.append((sub.name, None, type(e).__name__ + ": " + str(e)[:120]))
            any_failed = True

    index_dir = override_out if override_out is not None else parent
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / "index.md").write_text(render_index_md(rows), encoding="utf-8")
    if not quiet:
        print(f"index: {index_dir / 'index.md'}")
    return 1 if any_failed else 0


def _from_dict(d: dict) -> FlightReport:
    return FlightReport(
        schema_version=d["schema_version"],
        recording=d["recording"],
        dock_sn=d["dock_sn"],
        drone_sn=d.get("drone_sn"),
        started_at_ms=d["started_at_ms"],
        ended_at_ms=d["ended_at_ms"],
        duration_ms=d["duration_ms"],
        total_envelopes=d["total_envelopes"],
        envelope_counts_by_topic_key=d["envelope_counts_by_topic_key"],
        phase_transitions=d["phase_transitions"],
        verdicts=d["verdicts"],
        alert_decisions=d["alert_decisions"],
        metrics=FlightMetrics(**d["metrics"]),
    )


if __name__ == "__main__":
    sys.exit(main())
