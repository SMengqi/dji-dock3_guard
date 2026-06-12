"""Stage 3-D B1: 静态强制门 (设计 §12.4).

跑得快, 不依赖运行时. 用作 PR CI 第一道闸:
- (A) 禁止 MQTT 下发: src/ 不得出现 client.publish / mqtt.publish 等 (§0.2).
- (B) 原始 envelope 落盘只允许 ingest/replay_source.py (§0.4 契约).
- (C) custom_fn 引用必须落在 CUSTOM_FN_WHITELIST 集合内 (§5.4);
      禁止 dotted path / eval / exec 形式.

任一规则被破坏 PR 应当被拦. 失败时给具体行号 + 原因, 便于排查.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
CONFIG_DIR = REPO_ROOT / "config"


def _iter_py_files(root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


# ─── (A) 禁止 MQTT publish ────────────────────────────────────────


# 真实违规模式: client.publish(...) / mqtt.publish(...) / source.publish(...)
# EventBus.publish 是内存 pub-sub, 不是 MQTT publish; 排除它.
# notify channel 调 dingtalk/webhook 的 .post() / .request() 不算 publish.
_PUBLISH_PAT = re.compile(
    r"(?<![\w.])(?:client|mqtt|source|broker)\.publish\s*\("
)


class TestNoMqttPublish:
    """设计 §0.2 / §12.4: dock_guard 仅 SUBSCRIBE, 任何 publish 到 broker
    都是缺陷. 这是 spec 的硬约束."""

    def test_no_publish_in_src(self) -> None:
        offenders: list[str] = []
        for path in _iter_py_files(SRC_DIR):
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                if _PUBLISH_PAT.search(line):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{i}: {line.strip()}")
        assert not offenders, (
            "MQTT publish 命中 (违反 §0.2 / §12.4 'dock_guard 仅 SUBSCRIBE'); "
            "如确为 EventBus 等非 MQTT publish 误报, 改用 `bus.publish(` 命名:\n"
            + "\n".join(offenders)
        )


# ─── (B) 原始 envelope 落盘审计 ───────────────────────────────────


# 原始 envelope 落盘只允许 ingest/replay_source.py (它读取录制目录, 不写).
# 命中 'topics/' 子目录 / 显式 'raw_envelope' 标识算嫌疑.
_ENVELOPE_PATTERNS = [
    re.compile(r'topics/[^/\s"]+\.jsonl'),
    re.compile(r"raw_envelope"),
]

# 白名单: 允许 ingest 层读 recordings 但不写 (replay 模式).
_ENVELOPE_ALLOWLIST = {
    "src/dock_guard/ingest/replay_source.py",
    "src/dock_guard/ingest/source.py",   # 仅 Envelope 数据类定义
}


class TestNoRawEnvelopePersistence:
    """设计 §0.4 契约: dock_guard 不重复落盘原始 envelope. 录制职责归
    sim_dji_cloud_service. 这条与 §9.1 jsonl 表 (alerts/mutes/phase_transitions
    等) 没冲突, 后者是衍生审计数据."""

    def test_no_raw_envelope_writes_outside_allowlist(self) -> None:
        offenders: list[str] = []
        for path in _iter_py_files(SRC_DIR):
            rel = str(path.relative_to(REPO_ROOT))
            if rel in _ENVELOPE_ALLOWLIST:
                continue
            text = path.read_text(encoding="utf-8")
            for pat in _ENVELOPE_PATTERNS:
                for m in pat.finditer(text):
                    line_no = text.count("\n", 0, m.start()) + 1
                    offenders.append(f"{rel}:{line_no}: {m.group(0)}")
        assert not offenders, (
            "原始 envelope 持久化命中 (违反 §0.4); 允许列表:\n"
            f"  {sorted(_ENVELOPE_ALLOWLIST)}\n"
            "违规:\n" + "\n".join(offenders)
        )


# ─── (C) custom_fn 引用必须 ⊆ WHITELIST + 禁 dotted/eval/import ────


_CUSTOM_FN_REF_PAT = re.compile(r"custom_fn:\s*([A-Za-z_][A-Za-z0-9_]*)")
_CUSTOM_FN_DANGEROUS_PAT = re.compile(
    r"custom_fn:\s*[^#\n]*?(?:[./]|\bimport\b|\beval\b|\bexec\b)"
)


def _load_whitelist() -> set[str]:
    from dock_guard.rules.custom_fns import CUSTOM_FN_WHITELIST
    return {k.value for k in CUSTOM_FN_WHITELIST}


def _rules_yaml_text() -> str:
    path = CONFIG_DIR / "rules.yaml"
    if not path.exists():
        pytest.skip(f"rules.yaml not present: {path}")
    return path.read_text(encoding="utf-8")


class TestCustomFnWhitelist:
    """设计 §5.4 / §13.4.4: rules.yaml 引用的 custom_fn 必须落在
    Python 端 CUSTOM_FN_WHITELIST 集合内, 且形式必须是单纯 identifier,
    不许 dotted path / eval / import (防 yaml 任意指向 Python 函数)."""

    def test_all_refs_in_whitelist(self) -> None:
        text = _rules_yaml_text()
        whitelist = _load_whitelist()
        referenced = set(_CUSTOM_FN_REF_PAT.findall(text))
        bad = referenced - whitelist
        assert not bad, (
            f"rules.yaml 引用了不在白名单的 custom_fn: {sorted(bad)}\n"
            f"白名单: {sorted(whitelist)}\n"
            "新增 custom_fn 必须先在 src/dock_guard/rules/custom_fns.py "
            "的 CUSTOM_FN_WHITELIST 注册."
        )

    def test_no_dotted_or_eval_form(self) -> None:
        text = _rules_yaml_text()
        offenders: list[str] = []
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if _CUSTOM_FN_DANGEROUS_PAT.search(line):
                offenders.append(f"rules.yaml:{i}: {line.strip()}")
        assert not offenders, (
            "rules.yaml 出现疑似 dotted path / eval / import 形式 custom_fn 引用; "
            "spec §5.4 仅允许 identifier:\n" + "\n".join(offenders)
        )

    def test_yaml_parses_cleanly(self) -> None:
        """附带健康检查: rules.yaml 本身能被 yaml.safe_load 解析, 防 CI
        因为 yaml 损坏在更深的测试里报怪错."""
        text = _rules_yaml_text()
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as e:
            pytest.fail(f"rules.yaml 解析失败: {e}")
