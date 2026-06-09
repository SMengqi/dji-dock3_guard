"""Phase 4 单元测试: rules.yaml schema 校验 (设计 §5.7.1)."""

from __future__ import annotations

import pathlib
import textwrap

import pytest
import yaml as pyyaml
from pydantic import ValidationError

from dock_guard.rules.custom_fns import CustomFnEnum
from dock_guard.rules.loader import KNOWN_FACT_NAMES, RulesYaml, load_rules_yaml


def _wrap(rule_yaml: str, *, section: str = "preflight_block") -> dict:
    return pyyaml.safe_load(textwrap.dedent(f"""
        version: 2
        {section}:
          {rule_yaml}
    """))


class TestSchemaBasics:
    def test_version_must_be_2(self) -> None:
        with pytest.raises(ValidationError):
            RulesYaml.model_validate({"version": 1})

    def test_empty_sections_valid(self) -> None:
        cfg = RulesYaml.model_validate({"version": 2})
        assert list(cfg.all_rules()) == []

    def test_known_facts_includes_phase_3_subset(self) -> None:
        for fname in ("phase", "wind_gust_max_30s", "rtk_fixed", "cover_state"):
            assert fname in KNOWN_FACT_NAMES


class TestFactConditionValidation:
    def test_unknown_fact_rejected(self) -> None:
        data = _wrap("""
          - id: r1
            phase: [PREFLIGHT]
            all:
              - { fact: nonexistent_fact, op: ">", value: 1 }
            verdict: { level: block, code: X }
        """)
        with pytest.raises(ValidationError, match="unknown fact"):
            RulesYaml.model_validate(data)

    def test_must_have_exactly_one_of_value_factref_valueref(self) -> None:
        data = _wrap("""
          - id: r1
            all:
              - { fact: wind_gust_max_30s, op: ">" }
            verdict: { level: warn, code: X }
        """)
        with pytest.raises(ValidationError, match="exactly one of"):
            RulesYaml.model_validate(data)

    def test_fact_ref_valid(self) -> None:
        data = _wrap("""
          - id: r1
            all:
              - { fact: battery_capacity_percent, op: "<=", fact_ref: battery_return_home_power }
            verdict: { level: return, code: BAT_LOW }
        """)
        cfg = RulesYaml.model_validate(data)
        rule = next(cfg.all_rules())
        assert rule.all_ is not None
        assert rule.all_[0].fact_ref == "battery_return_home_power"

    def test_fact_ref_unknown_rejected(self) -> None:
        data = _wrap("""
          - id: r1
            all:
              - { fact: battery_capacity_percent, op: "<=", fact_ref: nonexistent }
            verdict: { level: warn, code: X }
        """)
        with pytest.raises(ValidationError, match="unknown fact_ref"):
            RulesYaml.model_validate(data)


class TestRuleValidation:
    def test_must_have_exactly_one_of_all_any_custom(self) -> None:
        data = _wrap("""
          - id: r1
            verdict: { level: warn, code: X }
        """)
        with pytest.raises(ValidationError, match="exactly one of"):
            RulesYaml.model_validate(data)

    def test_all_and_any_together_rejected(self) -> None:
        data = _wrap("""
          - id: r1
            all:  [{ fact: warming_up, op: "==", value: true }]
            any:  [{ fact: rtk_fixed, op: "==", value: false }]
            verdict: { level: warn, code: X }
        """)
        with pytest.raises(ValidationError, match="exactly one of"):
            RulesYaml.model_validate(data)

    def test_custom_fn_known_passes(self) -> None:
        data = _wrap("""
          - id: r1
            phase: [CRUISE]
            custom_fn: is_battery_drop_normal
            custom_args:
              window_ms: 60000
            verdict: { level: warn, code: BDR_ANOMALY }
        """)
        cfg = RulesYaml.model_validate(data)
        rule = next(cfg.all_rules())
        assert rule.custom_fn == CustomFnEnum.is_battery_drop_normal
        assert rule.custom_args == {"window_ms": 60000}

    def test_custom_fn_unknown_rejected(self) -> None:
        data = _wrap("""
          - id: r1
            custom_fn: hacked_function
            verdict: { level: warn, code: X }
        """)
        with pytest.raises(ValidationError):
            RulesYaml.model_validate(data)

    def test_custom_args_without_custom_fn_rejected(self) -> None:
        data = _wrap("""
          - id: r1
            all: [{ fact: warming_up, op: "==", value: true }]
            custom_args: { x: 1 }
            verdict: { level: warn, code: X }
        """)
        with pytest.raises(ValidationError, match="custom_args requires custom_fn"):
            RulesYaml.model_validate(data)


class TestUniqueIds:
    def test_duplicate_rule_id_rejected(self) -> None:
        data = {
            "version": 2,
            "preflight_block": [
                {"id": "dup", "all": [{"fact": "warming_up", "op": "==", "value": True}],
                 "verdict": {"level": "block", "code": "X"}},
            ],
            "inflight_escalate": [
                {"id": "dup", "all": [{"fact": "warming_up", "op": "==", "value": True}],
                 "verdict": {"level": "return", "code": "Y"}},
            ],
        }
        with pytest.raises(ValidationError, match="duplicate rule id"):
            RulesYaml.model_validate(data)


def test_real_rules_yaml_loads() -> None:
    repo = pathlib.Path(__file__).resolve().parents[2] / "config" / "rules.yaml"
    if not repo.exists():
        pytest.skip("config/rules.yaml not present")
    cfg = load_rules_yaml(repo)
    rules = list(cfg.all_rules())
    assert len(rules) >= 5
    ids = {r.id for r in rules}
    assert "maint.warming_up" in ids
