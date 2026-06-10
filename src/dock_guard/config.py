"""配置加载层 (Phase 1).

设计原则:
- 所有 yaml 启动期 pydantic 校验, 任一字段缺失/类型错 -> fail-fast.
- ${VAR} 占位符从 os.environ 展开, 缺失环境变量 -> fail-fast 并报具体变量名.
- 仓库只入 .example, 真实配置由 install.sh (默认开启 copy) 生成.

对应设计章节:
- runtime.yaml         §15.1
- mode_code_map.yaml   §4.4
- alert_levels.yaml    §6.2
- enums.yaml           §5.3
"""

from __future__ import annotations

import os
import pathlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dock_guard.types import ChannelKind, Severity, TopicKey

# ─────────────────────────────────────────────────────────────────────
# ${VAR} 展开
# ─────────────────────────────────────────────────────────────────────


class MissingEnvVarError(RuntimeError):
    """${VAR} 未注入环境变量."""

    def __init__(self, var_names: list[str], yaml_path: pathlib.Path | None = None) -> None:
        self.var_names = var_names
        self.yaml_path = yaml_path
        head = f"in {yaml_path}: " if yaml_path else ""
        super().__init__(f"{head}missing env vars: {', '.join(var_names)}")


_VAR_PATTERN = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")


def expand_env_vars(
    raw: str,
    env: Mapping[str, str] | None = None,
    *,
    yaml_path: pathlib.Path | None = None,
) -> str:
    """展开 ${VAR} 占位符. 任一变量未注入即抛 MissingEnvVarError.

    整行 YAML 注释 (以 # 起头, 可前置空格) 内的 ${VAR} 字面量不展开,
    避免模板示例文本被误判 (例如 `# 此处用 ${VAR} 占位`).
    """
    env_map = env if env is not None else os.environ
    missing: list[str] = []

    def _sub(m: re.Match[str]) -> str:
        var = m.group(1)
        if var not in env_map:
            missing.append(var)
            return m.group(0)
        return env_map[var]

    out_lines: list[str] = []
    for line in raw.splitlines(keepends=True):
        if line.lstrip().startswith("#"):
            out_lines.append(line)
            continue
        out_lines.append(_VAR_PATTERN.sub(_sub, line))
    result = "".join(out_lines)

    if missing:
        seen: set[str] = set()
        unique_missing = [v for v in missing if not (v in seen or seen.add(v))]
        raise MissingEnvVarError(unique_missing, yaml_path)
    return result


# ─────────────────────────────────────────────────────────────────────
# Pydantic schemas
# ─────────────────────────────────────────────────────────────────────


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ── runtime.yaml ────────────────────────────────────────────────────


class TLSConfig(_Strict):
    enabled: bool = True
    ca_cert_path: str = ""
    verify_hostname: bool = True


class ReconnectConfig(_Strict):
    initial_delay_s: int = Field(default=1, ge=0)
    max_delay_s: int = Field(default=60, ge=1)
    factor: int = Field(default=2, ge=1)


class MqttConfig(_Strict):
    broker_url: str = Field(min_length=1)
    # 空 / null = 不发 auth (sim 本地 mosquitto 默认无 auth);
    # 真 broker 由 broker 本身拒绝匿名, 而不是在此处强制 min_length=1.
    username: str = ""
    password: str = ""
    client_id_prefix: str = "dock_guard"
    tls: TLSConfig = TLSConfig()
    qos: int = Field(default=1, ge=0, le=2)
    reconnect: ReconnectConfig = ReconnectConfig()

    @field_validator("username", "password", mode="before")
    @classmethod
    def _none_to_empty(cls, v: object) -> object:
        """YAML 把空标量解析为 None (e.g. `username: ${MQTT_USERNAME}` 当 env 空时);
        统一归一成空串, 让下游 'or None' 的判断生效."""
        return "" if v is None else v


class TopicDefaults(_Strict):
    """全局 topic 默认开关 (§15.1). 字段名 = TopicKey 枚举值."""

    dock_osd: bool = True
    dock_state: bool = True
    dock_events: bool = True
    dock_requests: bool = True
    dock_requests_reply: bool = True
    dock_services_reply: bool = True
    dock_sys_status: bool = True
    drone_osd: bool = True
    drone_state: bool = True
    drone_state_reply: bool = False
    drone_events: bool = True
    dock_drc_up: bool = False
    dock_drc_down: bool = False
    dock_services: bool = False

    def as_map(self) -> dict[TopicKey, bool]:
        return {TopicKey(name): val for name, val in self.model_dump().items()}


class DockSubscription(_Strict):
    dock_sn: str = Field(min_length=1)
    enabled: bool = True
    # per-dock 覆盖. key 必须在 TopicKey 集合内.
    topics: dict[str, bool] | None = None

    @field_validator("dock_sn")
    @classmethod
    def _no_template_placeholder(cls, v: str) -> str:
        """模板未填的常见占位符 (REPLACE_WITH_*, TODO, <...>, ...) 启动期拒启.
        否则 MqttSource 会真去订一个不存在的 topic, 永远收不到数据,
        看上去"连上了 broker 但没动静"——非常难诊断."""
        s = v.strip()
        upper = s.upper()
        # 真实 DJI SN 是字母数字混排, 不会出现 REPLACE/TODO/FIXME 这些单词,
        # 故用 substring 命中即拒.
        bad_markers = ("REPLACE", "TODO", "FIXME", "FILL_ME", "FILL_IN")
        if any(m in upper for m in bad_markers):
            raise ValueError(
                f"dock_sn 看起来仍是模板占位符 {v!r}; "
                f"请把 runtime.yaml 的 subscriptions[].dock_sn 改成真实机场 SN "
                f"(例如 sim 录制样本: 8UUXN7N00A0GAA)"
            )
        if s.startswith("<") and s.endswith(">"):
            raise ValueError(f"dock_sn 看起来仍是 <占位符> {v!r}, 请填实际 SN")
        return v

    @field_validator("topics")
    @classmethod
    def _validate_topic_keys(cls, v: dict[str, bool] | None) -> dict[str, bool] | None:
        if v is None:
            return None
        valid = {k.value for k in TopicKey}
        unknown = [k for k in v if k not in valid]
        if unknown:
            raise ValueError(f"unknown topic keys: {unknown} (valid: {sorted(valid)})")
        return v

    def effective_topics(self, defaults: TopicDefaults) -> dict[TopicKey, bool]:
        """合并: defaults <- topics 覆盖."""
        result = defaults.as_map()
        if self.topics:
            for k, val in self.topics.items():
                result[TopicKey(k)] = val
        return result


class WildcardSubscribe(_Strict):
    enabled: bool = False


class RuntimeParams(_Strict):
    warming_up_ms: int = Field(default=60000, ge=0)
    bare_flight_threshold_ms: int = Field(default=5000, ge=0)
    dock_osd_silence_to_offline_ms: int = Field(default=10000, ge=1000)
    drone_osd_silence_alert_ms: int = Field(default=5000, ge=1000)
    facts_ring_window_max_ms: int = Field(default=300000, ge=1000)
    snapshot_persist_interval_s: int = Field(default=30, ge=1)


class RuntimeYaml(_Strict):
    schema_version: int = Field(ge=1, le=1)
    mqtt: MqttConfig
    topic_defaults: TopicDefaults = TopicDefaults()
    subscriptions: list[DockSubscription] = Field(min_length=0)
    wildcard_subscribe: WildcardSubscribe = WildcardSubscribe()
    runtime: RuntimeParams = RuntimeParams()

    @model_validator(mode="after")
    def _check_subscriptions_or_wildcard(self) -> RuntimeYaml:
        enabled = [s for s in self.subscriptions if s.enabled]
        if not enabled and not self.wildcard_subscribe.enabled:
            raise ValueError(
                "runtime.yaml must enable at least one subscription "
                "(set subscriptions[].enabled=true) or wildcard_subscribe.enabled=true"
            )
        return self


# ── mode_code_map.yaml ──────────────────────────────────────────────


class ModeCodeMapYaml(_Strict):
    drone_model: str
    firmware_min: str | None = None
    values: dict[int, str]
    airborne_set: list[int]
    phase_bucket: dict[str, list[int]]
    unknown_policy: str

    @field_validator("airborne_set")
    @classmethod
    def _airborne_unique(cls, v: list[int]) -> list[int]:
        if len(v) != len(set(v)):
            raise ValueError("airborne_set must have unique values")
        return v

    @model_validator(mode="after")
    def _values_cover_buckets(self) -> ModeCodeMapYaml:
        defined = set(self.values.keys())
        for phase, codes in self.phase_bucket.items():
            unknown = [c for c in codes if c not in defined]
            if unknown:
                raise ValueError(
                    f"phase_bucket.{phase} references undefined mode_code(s): {unknown}"
                )
        return self


# ── alert_levels.yaml ───────────────────────────────────────────────


class LevelRouting(_Strict):
    channels: list[ChannelKind] = Field(min_length=0)
    dingtalk_repeat: int = Field(default=1, ge=1)
    dingtalk_repeat_interval_s: int = Field(default=30, ge=1)
    dingtalk_at_all: bool = False


class CoordinatorParams(_Strict):
    default_cooldown_ms: int = Field(default=30000, ge=0)
    emergency_floor_cooldown_ms: int = Field(default=2000, ge=0)
    dedup_window_ms: int = Field(default=60000, ge=1000)
    dedup_burst_threshold: int = Field(default=10, ge=1)


class AlertLevelsYaml(_Strict):
    version: int = Field(ge=2, le=2)
    level_routing_defaults: dict[str, LevelRouting]
    coordinator: CoordinatorParams = CoordinatorParams()

    @model_validator(mode="after")
    def _all_severities_covered(self) -> AlertLevelsYaml:
        required = {s.name.lower() for s in Severity}
        present = set(self.level_routing_defaults.keys())
        missing = required - present
        if missing:
            raise ValueError(
                f"alert_levels.yaml.level_routing_defaults missing severities: {sorted(missing)}"
            )
        return self


# ── enums.yaml ──────────────────────────────────────────────────────


class EnumsYaml(_Strict):
    version: int = Field(ge=1, le=1)
    rainfall_trend: dict[str, int]
    data_freshness: dict[str, int]


# ─────────────────────────────────────────────────────────────────────
# 文件 IO
# ─────────────────────────────────────────────────────────────────────


def _load_yaml_with_env(path: pathlib.Path, env: Mapping[str, str] | None = None) -> object:
    """读 yaml, 展开 ${VAR}, 返回 Python 对象."""
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")
    raw = path.read_text(encoding="utf-8")
    expanded = expand_env_vars(raw, env, yaml_path=path)
    return yaml.safe_load(expanded)


def load_runtime_yaml(path: pathlib.Path, env: Mapping[str, str] | None = None) -> RuntimeYaml:
    return RuntimeYaml.model_validate(_load_yaml_with_env(path, env))


def load_mode_code_map(path: pathlib.Path) -> ModeCodeMapYaml:
    return ModeCodeMapYaml.model_validate(_load_yaml_with_env(path))


def load_alert_levels(path: pathlib.Path) -> AlertLevelsYaml:
    return AlertLevelsYaml.model_validate(_load_yaml_with_env(path))


def load_enums(path: pathlib.Path) -> EnumsYaml:
    return EnumsYaml.model_validate(_load_yaml_with_env(path))


# ─────────────────────────────────────────────────────────────────────
# 顶层聚合: AppConfig
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AppConfig:
    """启动期所有必要配置的聚合.

    可选 yaml (battery_reference / drone_kinematics / hms_codes / webhooks)
    在后续 phase 扩展.
    """

    config_dir: pathlib.Path
    runtime: RuntimeYaml
    mode_code_map: ModeCodeMapYaml
    alert_levels: AlertLevelsYaml
    enums: EnumsYaml
    rules: Any = None                   # RulesYaml; Phase 4+ 加载
    dingtalk_robots: Any = None         # DingTalkRobotsYaml | None; 文件缺失 = 不开钉钉通道
    notification_routing: Any = None    # NotificationRoutingYaml | None; 缺失 = 用 alert_levels 默认路由


def load_app_config(
    config_dir: pathlib.Path,
    *,
    env: Mapping[str, str] | None = None,
    with_rules: bool = True,
) -> AppConfig:
    """加载所有必备 yaml. 任一缺失/校验错 -> fail-fast.

    通知层 yaml (dingtalk_robots / notification_routing) **文件缺失视为可选**:
    缺 dingtalk_robots.yaml -> 不开钉钉通道, 仅入 alerts.jsonl;
    存在但 ${VAR} 未注入或 schema 错 -> 仍 fail-fast (避免无声空跑).
    """
    from dock_guard.notify.loader import (  # 延迟 import 避免循环
        load_dingtalk_robots,
        load_notification_routing,
    )
    from dock_guard.rules.loader import load_rules_yaml

    rules = None
    if with_rules:
        rules = load_rules_yaml(config_dir / "rules.yaml")

    dingtalk_path = config_dir / "dingtalk_robots.yaml"
    dingtalk = load_dingtalk_robots(dingtalk_path, env) if dingtalk_path.exists() else None

    routing_path = config_dir / "notification_routing.yaml"
    routing = load_notification_routing(routing_path) if routing_path.exists() else None

    return AppConfig(
        config_dir=config_dir,
        runtime=load_runtime_yaml(config_dir / "runtime.yaml", env),
        mode_code_map=load_mode_code_map(config_dir / "mode_code_map.yaml"),
        alert_levels=load_alert_levels(config_dir / "alert_levels.yaml"),
        enums=load_enums(config_dir / "enums.yaml"),
        rules=rules,
        dingtalk_robots=dingtalk,
        notification_routing=routing,
    )
