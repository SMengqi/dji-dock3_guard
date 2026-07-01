"""飞行复盘 web 查看器 CLI 入口 (只读, 无鉴权).

用法:
    python -m dock_guard.analytics.serve <reports_root>
    python -m dock_guard.analytics.serve <reports_root> --host 127.0.0.1 --port 8080

<reports_root> = 批量分析父目录, 含 <recording>/dock_guard_report/report.json.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

from dock_guard.analytics.serve.app import build_report_app


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dock_guard.analytics.serve",
        description="飞行复盘报告 web 查看器 (只读, 无鉴权, 内网用).",
    )
    p.add_argument("reports_root", type=Path,
                   help="批量分析父目录 (含 <recording>/dock_guard_report/report.json)")
    p.add_argument("--host", default="0.0.0.0", help="监听地址 (默认 0.0.0.0)")
    p.add_argument("--port", type=int, default=8080, help="监听端口 (默认 8080)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.reports_root.resolve()
    if not root.is_dir():
        print(f"reports_root 不存在或非目录: {root}", file=sys.stderr)
        return 2
    app = build_report_app(root)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
