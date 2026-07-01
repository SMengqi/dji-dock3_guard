"""飞行复盘 web 查看器 FastAPI app factory (只读, 无鉴权).

build_report_app(reports_root) 装:
  GET /api/reports            → scanner.scan_reports (摘要清单)
  GET /api/reports/{name}     → 原样透传 report.json (FileResponse)
  GET /                       → static/index.html   (Task 3)
  GET /r/{name}               → static/detail.html  (Task 3)
  /static/*                   → StaticFiles          (Task 3)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from dock_guard.analytics.serve.scanner import resolve_report, scan_reports

_STATIC = Path(__file__).parent / "static"


def build_report_app(reports_root: Path) -> FastAPI:
    app = FastAPI(title="dock_guard 飞行复盘查看器", version="1.0", docs_url=None)

    @app.get("/api/reports")
    def api_reports() -> list[dict[str, Any]]:
        return scan_reports(reports_root)

    @app.get("/api/reports/{recording}")
    def api_report(recording: str) -> FileResponse:
        rp = resolve_report(reports_root, recording)
        if rp is None:
            raise HTTPException(status_code=404, detail="report not found")
        return FileResponse(rp, media_type="application/json")

    return app
