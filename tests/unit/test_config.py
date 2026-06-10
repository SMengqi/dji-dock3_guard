"""Phase 1 单元测试: config 加载与 ${VAR} 展开 (设计 §15.1 / §10.1)."""

from __future__ import annotations

import pathlib
import textwrap

import pytest
from pydantic import ValidationError

from dock_guard.config import (
    AlertLevelsYaml,
    DockSubscription,
    MissingEnvVarError,
    ModeCodeMapYaml,
    TopicDefaults,
    expand_env_vars,
    load_alert_levels,
    load_app_config,
    load_enums,
    load_mode_code_map,
    load_runtime_yaml,
)
from dock_guard.types import TopicKey


class TestExpandEnvVars:
    def test_simple_expansion(self) -> None:
        out = expand_env_vars("hello ${X}!", env={"X": "world"})
        assert out == "hello world!"

    def test_multiple_vars(self) -> None:
        out = expand_env_vars("${A}_${B}", env={"A": "foo", "B": "bar"})
        assert out == "foo_bar"

    def test_missing_var_raises_with_name(self) -> None:
        with pytest.raises(MissingEnvVarError) as exc:
            expand_env_vars("hi ${MISSING}", env={})
        assert exc.value.var_names == ["MISSING"]

    def test_missing_multiple_dedup(self) -> None:
        with pytest.raises(MissingEnvVarError) as exc:
            expand_env_vars("${A} ${B} ${A} ${C}", env={"B": "ok"})
        assert exc.value.var_names == ["A", "C"]

    def test_no_placeholders_passthrough(self) -> None:
        assert expand_env_vars("plain text", env={}) == "plain text"

    def test_comment_lines_not_expanded(self) -> None:
        """# 起头的整行 YAML 注释里的 ${VAR} 不应触发展开 / 不应入 missing."""
        raw = (
            "# this comment mentions ${VAR} as a literal placeholder\n"
            "   # indented comment too: ${OTHER}\n"
            "real: ${REAL}\n"
        )
        out = expand_env_vars(raw, env={"REAL": "x"})
        assert "${VAR}" in out             # 注释保留原貌
        assert "${OTHER}" in out
        assert "real: x" in out

    def test_comment_isolated_missing_var_does_not_raise(self) -> None:
        raw = "# 用 ${SHOULD_BE_IGNORED} 占位\nreal: hi\n"
        # 注释里的占位符不应让本来无 ${} 的 yaml 报错.
        assert expand_env_vars(raw, env={}).startswith("# 用 ${SHOULD_BE_IGNORED}")


def _minimal_runtime_yaml(*, dock_sn: str = "TEST_DOCK_01") -> str:
    return textwrap.dedent(f"""
        schema_version: 1
        mqtt:
          broker_url:  ${{MQTT_BROKER_URL}}
          username:    ${{MQTT_USERNAME}}
          password:    ${{MQTT_PASSWORD}}
        subscriptions:
          - dock_sn: {dock_sn}
            enabled: true
    """)


_GOOD_ENV = {
    "MQTT_BROKER_URL": "ssl://broker.test:8883",
    "MQTT_USERNAME": "test_user",
    "MQTT_PASSWORD": "test_pass",
}


class TestLoadRuntimeYaml:
    def test_happy_path(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "runtime.yaml"
        path.write_text(_minimal_runtime_yaml())
        cfg = load_runtime_yaml(path, env=_GOOD_ENV)
        assert cfg.schema_version == 1
        assert cfg.mqtt.broker_url == "ssl://broker.test:8883"
        assert cfg.mqtt.username == "test_user"
        assert cfg.mqtt.password == "test_pass"
        assert len(cfg.subscriptions) == 1
        assert cfg.subscriptions[0].dock_sn == "TEST_DOCK_01"

    def test_defaults_topic_defaults(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "runtime.yaml"
        path.write_text(_minimal_runtime_yaml())
        cfg = load_runtime_yaml(path, env=_GOOD_ENV)
        td = cfg.topic_defaults
        assert td.dock_osd is True
        assert td.dock_drc_up is False
        assert td.dock_services is False
        assert td.drone_state_reply is False

    def test_missing_env_var_fails(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "runtime.yaml"
        path.write_text(_minimal_runtime_yaml())
        with pytest.raises(MissingEnvVarError) as exc:
            load_runtime_yaml(path, env={})
        assert "MQTT_BROKER_URL" in exc.value.var_names

    def test_no_enabled_subscription_fails(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "runtime.yaml"
        path.write_text(textwrap.dedent("""
            schema_version: 1
            mqtt:
              broker_url:  url
              username:    u
              password:    p
            subscriptions:
              - dock_sn: SN1
                enabled: false
        """))
        with pytest.raises(ValidationError, match="at least one subscription"):
            load_runtime_yaml(path)

    def test_unknown_topic_key_fails(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "runtime.yaml"
        path.write_text(textwrap.dedent("""
            schema_version: 1
            mqtt:
              broker_url:  ${MQTT_BROKER_URL}
              username:    ${MQTT_USERNAME}
              password:    ${MQTT_PASSWORD}
            subscriptions:
              - dock_sn: SN1
                enabled: true
                topics:
                  nonexistent_topic: true
        """))
        with pytest.raises(ValidationError, match="unknown topic keys"):
            load_runtime_yaml(path, env=_GOOD_ENV)

    def test_empty_username_password_allowed(self, tmp_path: pathlib.Path) -> None:
        """sim 本地 mosquitto 无 auth: 空 username/password 应通过校验."""
        path = tmp_path / "runtime.yaml"
        path.write_text(textwrap.dedent("""
            schema_version: 1
            mqtt:
              broker_url:  tcp://localhost:1883
              username:    ""
              password:    ""
            subscriptions:
              - dock_sn: SIM_DOCK
                enabled: true
        """))
        cfg = load_runtime_yaml(path)
        assert cfg.mqtt.username == ""
        assert cfg.mqtt.password == ""

    def test_null_username_password_normalized_to_empty(
        self, tmp_path: pathlib.Path
    ) -> None:
        """YAML 空标量解析为 None (例如 ${VAR} 展开为空时),
        应统一归一为 ""."""
        path = tmp_path / "runtime.yaml"
        path.write_text(textwrap.dedent("""
            schema_version: 1
            mqtt:
              broker_url:  tcp://localhost:1883
              username:
              password:
            subscriptions:
              - dock_sn: SIM_DOCK
                enabled: true
        """))
        cfg = load_runtime_yaml(path)
        assert cfg.mqtt.username == ""
        assert cfg.mqtt.password == ""

    def test_wildcard_alone_is_valid(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "runtime.yaml"
        path.write_text(textwrap.dedent("""
            schema_version: 1
            mqtt:
              broker_url:  url
              username:    u
              password:    p
            subscriptions: []
            wildcard_subscribe:
              enabled: true
        """))
        cfg = load_runtime_yaml(path)
        assert cfg.wildcard_subscribe.enabled is True


class TestDockSubscriptionPlaceholder:
    """模板未填 dock_sn 应启动期拒启 (避免订阅一个不存在的 topic 静默吃数据)."""

    def test_replace_with_real_dock_sn_fails(self) -> None:
        with pytest.raises(ValidationError, match="模板占位符"):
            DockSubscription(dock_sn="REPLACE_WITH_REAL_DOCK_SN")

    def test_replace_marker_anywhere_fails(self) -> None:
        with pytest.raises(ValidationError, match="模板占位符"):
            DockSubscription(dock_sn="REPLACE_ME")

    def test_todo_marker_fails(self) -> None:
        with pytest.raises(ValidationError, match="模板占位符"):
            DockSubscription(dock_sn="TODO_FILL_DOCK_SN")

    def test_angle_bracket_placeholder_fails(self) -> None:
        with pytest.raises(ValidationError, match="<占位符>"):
            DockSubscription(dock_sn="<your-dock-sn>")

    def test_real_sn_passes(self) -> None:
        sub = DockSubscription(dock_sn="8UUXN7N00A0GAA")
        assert sub.dock_sn == "8UUXN7N00A0GAA"


class TestDockSubscriptionOverride:
    def test_effective_topics_merges(self) -> None:
        defaults = TopicDefaults()
        sub = DockSubscription(dock_sn="SN1", topics={"dock_drc_up": True})
        eff = sub.effective_topics(defaults)
        assert eff[TopicKey.DOCK_DRC_UP] is True
        assert eff[TopicKey.DOCK_OSD] is True  # 其它保持默认

    def test_effective_topics_no_override(self) -> None:
        defaults = TopicDefaults()
        sub = DockSubscription(dock_sn="SN1")
        eff = sub.effective_topics(defaults)
        assert eff == defaults.as_map()


def test_real_mode_code_map_loads() -> None:
    repo_config = pathlib.Path(__file__).resolve().parents[2] / "config" / "mode_code_map.yaml"
    if not repo_config.exists():
        pytest.skip(f"config not found: {repo_config}")
    m = load_mode_code_map(repo_config)
    assert m.drone_model == "M4D"
    assert len(m.values) == 22  # 0..21
    assert 9 in m.airborne_set
    assert "PREFLIGHT" in m.phase_bucket


def test_real_alert_levels_loads() -> None:
    repo_config = pathlib.Path(__file__).resolve().parents[2] / "config" / "alert_levels.yaml"
    if not repo_config.exists():
        pytest.skip(f"config not found: {repo_config}")
    al = load_alert_levels(repo_config)
    assert al.version == 2
    assert "emergency" in al.level_routing_defaults
    assert al.coordinator.emergency_floor_cooldown_ms == 2000


def test_real_enums_loads() -> None:
    repo_config = pathlib.Path(__file__).resolve().parents[2] / "config" / "enums.yaml"
    if not repo_config.exists():
        pytest.skip(f"config not found: {repo_config}")
    e = load_enums(repo_config)
    assert e.rainfall_trend["ESCALATING"] == 1
    assert e.rainfall_trend["RECEDING"] == -1


class TestModeCodeMapValidation:
    def test_phase_bucket_references_undefined_fails(self) -> None:
        with pytest.raises(ValidationError, match="undefined mode_code"):
            ModeCodeMapYaml.model_validate({
                "drone_model": "M4D",
                "values": {0: "STANDBY"},
                "airborne_set": [],
                "phase_bucket": {"CRUISE": [99]},
                "unknown_policy": "WARN_AND_TREAT_AS_AIRBORNE",
            })

    def test_airborne_set_duplicates_fails(self) -> None:
        with pytest.raises(ValidationError, match="unique"):
            ModeCodeMapYaml.model_validate({
                "drone_model": "M4D",
                "values": {0: "A", 1: "B"},
                "airborne_set": [0, 0, 1],
                "phase_bucket": {},
                "unknown_policy": "X",
            })


class TestAlertLevelsValidation:
    def test_missing_severity_fails(self) -> None:
        with pytest.raises(ValidationError, match="missing severities"):
            AlertLevelsYaml.model_validate({
                "version": 2,
                "level_routing_defaults": {
                    "emergency": {"channels": ["panel"]},
                    "block": {"channels": ["panel"]},
                },
            })


def test_load_app_config_with_repo_configs(tmp_path: pathlib.Path) -> None:
    repo_config_dir = pathlib.Path(__file__).resolve().parents[2] / "config"
    if not (repo_config_dir / "mode_code_map.yaml").exists():
        pytest.skip("repo config dir not present")

    for name in ("mode_code_map.yaml", "alert_levels.yaml", "enums.yaml"):
        (tmp_path / name).symlink_to(repo_config_dir / name)
    (tmp_path / "runtime.yaml").write_text(_minimal_runtime_yaml())

    cfg = load_app_config(tmp_path, env=_GOOD_ENV, with_rules=False)
    assert cfg.runtime.mqtt.broker_url == "ssl://broker.test:8883"
    assert cfg.mode_code_map.drone_model == "M4D"
    assert cfg.alert_levels.coordinator.emergency_floor_cooldown_ms == 2000
    assert cfg.enums.rainfall_trend["ESCALATING"] == 1
    # M1: 钉钉/路由 yaml 不在 tmp_path 中, 应降级为 None.
    assert cfg.dingtalk_robots is None
    assert cfg.notification_routing is None


# ── M1: notification yaml 可选加载 ──────────────────────────────────


_M1_ENV = {
    **_GOOD_ENV,
    "DINGTALK_BOT_WEBHOOK_PRIMARY": "https://oapi.dingtalk.com/robot/send?access_token=fake",
    "DINGTALK_BOT_SECRET_PRIMARY": "SECfake",
}


def _seed_min_configs(dst: pathlib.Path, repo_config_dir: pathlib.Path) -> None:
    """把仓库内固定 yaml symlink 到 dst, 再写最小 runtime.yaml."""
    for name in ("mode_code_map.yaml", "alert_levels.yaml", "enums.yaml"):
        (dst / name).symlink_to(repo_config_dir / name)
    (dst / "runtime.yaml").write_text(_minimal_runtime_yaml())


class TestNotificationConfigLoading:
    def _repo_config_dir(self) -> pathlib.Path:
        return pathlib.Path(__file__).resolve().parents[2] / "config"

    def test_dingtalk_yaml_present_loads(self, tmp_path: pathlib.Path) -> None:
        repo = self._repo_config_dir()
        if not (repo / "mode_code_map.yaml").exists():
            pytest.skip("repo config dir not present")
        _seed_min_configs(tmp_path, repo)
        (tmp_path / "dingtalk_robots.yaml").write_text(textwrap.dedent("""
            version: 1
            robots:
              - id: ops-primary
                webhook_url: ${DINGTALK_BOT_WEBHOOK_PRIMARY}
                secret:      ${DINGTALK_BOT_SECRET_PRIMARY}
                min_severity: WARN
        """))
        cfg = load_app_config(tmp_path, env=_M1_ENV, with_rules=False)
        assert cfg.dingtalk_robots is not None
        assert len(cfg.dingtalk_robots.robots) == 1
        assert cfg.dingtalk_robots.robots[0].id == "ops-primary"
        assert cfg.dingtalk_robots.robots[0].webhook_url.endswith("fake")
        assert cfg.notification_routing is None

    def test_dingtalk_yaml_missing_env_var_fails(self, tmp_path: pathlib.Path) -> None:
        """文件存在但 ${VAR} 未注入应 fail-fast, 不能静默降级."""
        repo = self._repo_config_dir()
        if not (repo / "mode_code_map.yaml").exists():
            pytest.skip("repo config dir not present")
        _seed_min_configs(tmp_path, repo)
        (tmp_path / "dingtalk_robots.yaml").write_text(textwrap.dedent("""
            version: 1
            robots:
              - id: ops-primary
                webhook_url: ${DINGTALK_BOT_WEBHOOK_PRIMARY}
                secret:      ${DINGTALK_BOT_SECRET_PRIMARY}
        """))
        with pytest.raises(MissingEnvVarError) as exc:
            load_app_config(tmp_path, env=_GOOD_ENV, with_rules=False)
        assert "DINGTALK_BOT_WEBHOOK_PRIMARY" in exc.value.var_names

    def test_routing_yaml_present_loads(self, tmp_path: pathlib.Path) -> None:
        repo = self._repo_config_dir()
        if not (repo / "mode_code_map.yaml").exists():
            pytest.skip("repo config dir not present")
        _seed_min_configs(tmp_path, repo)
        (tmp_path / "notification_routing.yaml").write_text(textwrap.dedent("""
            version: 1
            overrides:
              WIND_EXCEEDED_INFLIGHT:
                channels: [dingtalk]
                dingtalk_robots: [ops-primary]
        """))
        cfg = load_app_config(tmp_path, env=_GOOD_ENV, with_rules=False)
        assert cfg.notification_routing is not None
        assert "WIND_EXCEEDED_INFLIGHT" in cfg.notification_routing.overrides
