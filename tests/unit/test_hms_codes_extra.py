"""hms_codes_extra.js 格式守护 — 前端 hmsText() 回退查表依赖其结构."""

import json
import pathlib
import re

_JS = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src/dock_guard/analytics/serve/static/hms_codes_extra.js"
)


def _load_map() -> dict:
    text = _JS.read_text(encoding="utf-8")
    m = re.search(r"window\.HMS_TEXT_EXTRA\s*=\s*(\{.*\});", text, re.DOTALL)
    assert m, "找不到 window.HMS_TEXT_EXTRA 赋值"
    return json.loads(m.group(1))


def test_extra_map_parses_and_nonempty():
    m = _load_map()
    assert len(m) == 12


def test_extra_keys_are_lowercase_hex_codes():
    for key, val in _load_map().items():
        assert re.fullmatch(r"0x[0-9a-f]{8}", key), key
        assert isinstance(val, str) and val


def test_extra_covers_dock3_supplement_codes():
    m = _load_map()
    for code in ("0x19113c05", "0x19114816", "0x1d0c0006"):
        assert code in m
