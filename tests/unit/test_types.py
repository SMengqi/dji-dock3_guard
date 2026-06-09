"""Phase 1 单元测试: 枚举一致性 (设计 §3.2 / §4.0 / §5.4)."""

from __future__ import annotations

from dock_guard.types import (
    DRONE_SN_TOPICS,
    TOPIC_TEMPLATES,
    CoverState,
    DroneModeCode,
    FlightTaskStepCode,
    Phase,
    PhaseSource,
    Rainfall,
    RtkFixedCode,
    Severity,
    TopicKey,
    WindDirection,
)


class TestSeverity:
    def test_strict_order(self) -> None:
        # 设计 §5.4: emergency > block > return > warn > info
        assert (
            Severity.EMERGENCY
            > Severity.BLOCK
            > Severity.RETURN
            > Severity.WARN
            > Severity.INFO
        )

    def test_all_five_levels(self) -> None:
        assert len(Severity) == 5


class TestPhase:
    def test_canonical_ten_phases(self) -> None:
        # 设计 §4.0: 10 档
        assert len(Phase) == 10
        assert "BARE_FLIGHT" not in {p.name for p in Phase}, \
            "v1 BARE_FLIGHT 必须拆为 phase_source, 不在 Phase enum 中"

    def test_phase_source_three_kinds(self) -> None:
        assert len(PhaseSource) == 3


class TestDroneModeCode:
    def test_22_values(self) -> None:
        # 设计 §4.4: 21 档 + CN 文档新增 21 = 22 档
        assert len(DroneModeCode) == 22

    def test_known_critical_codes(self) -> None:
        assert DroneModeCode.STANDBY.value == 0
        assert DroneModeCode.AUTO_RTH.value == 9
        assert DroneModeCode.AUTO_LANDING.value == 10
        assert DroneModeCode.LIVE_FLIGHT_CONTROLS.value == 17


class TestFieldEnums:
    def test_rainfall_four_levels(self) -> None:
        assert Rainfall.HEAVY.value == 3

    def test_cover_state_four_levels(self) -> None:
        assert CoverState.ABNORMAL.value == 3

    def test_rtk_fixed_code(self) -> None:
        # 设计 §3.2.1: is_fixed==2 才算 rtk_fixed
        assert RtkFixedCode.FIXING_SUCCESSFUL.value == 2

    def test_wind_direction_eight_positions(self) -> None:
        assert len(WindDirection) == 8
        assert WindDirection.TRUE_NORTH.value == 1  # 不是 0

    def test_flighttask_step_code_includes_255(self) -> None:
        # 设计 §3.2.2: 255 = Aircraft abnormal
        assert FlightTaskStepCode.AIRCRAFT_ABNORMAL.value == 255


class TestTopicKeys:
    def test_14_topics(self) -> None:
        # 设计 §15.1.1
        assert len(TopicKey) == 14

    def test_all_keys_have_template(self) -> None:
        for key in TopicKey:
            assert key in TOPIC_TEMPLATES, f"missing template for {key}"
            assert TOPIC_TEMPLATES[key].count("{") > 0, \
                f"template for {key} must contain placeholder"

    def test_drone_sn_topics_subset(self) -> None:
        assert DRONE_SN_TOPICS.issubset(set(TopicKey))
        for key in TopicKey:
            if key.value.startswith("drone_"):
                assert key in DRONE_SN_TOPICS

    def test_dock_services_template_exists(self) -> None:
        # 设计 §0.2 / §15.1.1: dock_services 只允许观测订阅, 不在 publish 路径
        assert TopicKey.DOCK_SERVICES in TopicKey
        assert "services" in TOPIC_TEMPLATES[TopicKey.DOCK_SERVICES]
