#!/usr/bin/env python3
"""gen_hms_codes — 从 DJI hms.json 语言包生成前端 HMS 文案映射.

来源: DJI 公开 CloudAPI SDK 语言包 hms.json
  https://terra-1-g.djicdn.com/fee90c2e03e04e8da67ea6f56365fc76/SDK 文档/CloudAPI/hms.json
生成日期: 2026-07-06

只取 fpv_tip_/dock_tip_ 前缀且有 zh 文案的条目, key 统一小写,
写出 static/hms_codes.js 供安全视图 HMS 面板 tooltip 查表.

用法:
    python scripts/gen_hms_codes.py <hms.json 路径> [输出路径]
"""

from __future__ import annotations

import argparse
import json
import pathlib

_DEFAULT_OUT = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src/dock_guard/analytics/serve/static/hms_codes.js"
)


def build_map(data: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, val in data.items():
        if not (key.startswith("fpv_tip_") or key.startswith("dock_tip_")):
            continue
        if not isinstance(val, dict):
            continue
        zh = val.get("zh")
        if not zh:
            continue
        out[key.lower()] = zh
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("hms_json", type=pathlib.Path)
    ap.add_argument("out", type=pathlib.Path, nargs="?", default=_DEFAULT_OUT)
    args = ap.parse_args()
    data = json.loads(args.hms_json.read_text(encoding="utf-8"))
    m = build_map(data)
    body = json.dumps(m, ensure_ascii=False, sort_keys=True)
    args.out.write_text(f"window.HMS_TEXT = {body};\n", encoding="utf-8")
    print(f"hms_codes.js: {len(m)} 条 -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
