"""HTTP host/port 解析的单测 (.env -> args -> 硬编码)."""

from __future__ import annotations

from dock_guard.__main__ import _parse_port_env


class TestParsePortEnv:
    def test_none_returns_none(self) -> None:
        assert _parse_port_env(None) is None

    def test_empty_returns_none(self) -> None:
        assert _parse_port_env("") is None

    def test_whitespace_returns_none(self) -> None:
        assert _parse_port_env("   ") is None

    def test_non_digit_returns_none(self) -> None:
        assert _parse_port_env("abc") is None
        assert _parse_port_env("80x") is None

    def test_valid_returns_int(self) -> None:
        assert _parse_port_env("8082") == 8082

    def test_trims_whitespace(self) -> None:
        assert _parse_port_env("  9000  ") == 9000
