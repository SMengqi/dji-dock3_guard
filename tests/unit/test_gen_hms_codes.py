import importlib.util
import pathlib

_SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "gen_hms_codes.py"


def _load():
    spec = importlib.util.spec_from_file_location("gen_hms_codes", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_map_keeps_fpv_dock_with_zh():
    mod = _load()
    data = {
        "fpv_tip_0x1B030019": {"en": "off route", "zh": "已偏离航线"},
        "dock_tip_0x12040000": {"zh": "RTK设备断开"},
    }
    m = mod.build_map(data)
    assert m["fpv_tip_0x1b030019"] == "已偏离航线"
    assert m["dock_tip_0x12040000"] == "RTK设备断开"


def test_build_map_lowercases_key():
    mod = _load()
    m = mod.build_map({"fpv_tip_0x1E010004": {"zh": "低电量"}})
    assert "fpv_tip_0x1e010004" in m
    assert "fpv_tip_0x1E010004" not in m


def test_build_map_skips_no_zh():
    mod = _load()
    m = mod.build_map({"fpv_tip_0xAAAA": {"en": "only en"}})
    assert m == {}


def test_build_map_skips_non_tip_prefix():
    mod = _load()
    m = mod.build_map({"some_other_0x1": {"zh": "无关"}})
    assert m == {}
