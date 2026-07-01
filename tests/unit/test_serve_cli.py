"""serve.__main__: argparse + 启动前校验 (不真起 uvicorn)."""

from __future__ import annotations

from pathlib import Path

from dock_guard.analytics.serve.__main__ import build_parser, main
from tests.unit._serve_helpers import write_sample_report


def test_parser_defaults() -> None:
    args = build_parser().parse_args(["/some/root"])
    assert args.host == "0.0.0.0"
    assert args.port == 8080
    assert str(args.reports_root) == "/some/root"


def test_main_missing_root_returns_2(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    assert main([str(missing)]) == 2


def test_main_valid_root_runs_and_returns_0(tmp_path: Path, monkeypatch) -> None:
    write_sample_report(tmp_path, "rec1")
    called = {}

    def fake_run(app, host, port):
        called["host"] = host
        called["port"] = port

    import dock_guard.analytics.serve.__main__ as mod
    monkeypatch.setattr(mod.uvicorn, "run", fake_run)
    assert main([str(tmp_path), "--port", "9999"]) == 0
    assert called["port"] == 9999
