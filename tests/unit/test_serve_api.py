"""serve.app: API 契约 (清单 / 透传 / 404 / 路径安全)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from dock_guard.analytics.serve.app import build_report_app
from tests.unit._serve_helpers import write_sample_report


def _client(tmp_path: Path) -> TestClient:
    write_sample_report(tmp_path, "rec1")
    return TestClient(build_report_app(tmp_path))


def test_api_reports_list(tmp_path: Path) -> None:
    c = _client(tmp_path)
    rows = c.get("/api/reports").json()
    assert rows[0]["recording"] == "rec1"
    assert rows[0]["ok"] is True


def test_api_report_passthrough(tmp_path: Path) -> None:
    c = _client(tmp_path)
    resp = c.get("/api/reports/rec1")
    assert resp.status_code == 200
    d = resp.json()
    assert d["schema_version"] == 3
    assert d["dock_sn"] == "DOCK_SN"
    assert len(d["battery_samples"]) == 2


def test_api_report_missing_404(tmp_path: Path) -> None:
    c = _client(tmp_path)
    assert c.get("/api/reports/nope").status_code == 404


def test_api_report_traversal_404(tmp_path: Path) -> None:
    c = _client(tmp_path)
    # 编码后的 ../ 也必须挡住
    assert c.get("/api/reports/..%2F..%2Fetc").status_code == 404


def test_index_html(tmp_path: Path) -> None:
    c = _client(tmp_path)
    resp = c.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_detail_html(tmp_path: Path) -> None:
    c = _client(tmp_path)
    resp = c.get("/r/rec1")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_static_app_js_served(tmp_path: Path) -> None:
    c = _client(tmp_path)
    resp = c.get("/static/app.js")
    assert resp.status_code == 200
    assert "renderDetail" in resp.text
