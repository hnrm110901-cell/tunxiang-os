"""
Feature Flag Client 单元测试

覆盖：
- Flag 默认值正确（dev/prod 环境差异）
- 环境变量覆盖有效（最高优先级）
- targeting_rules 评估（brand_id / store_id / role_code 维度）
- 未定义 Flag 返回 False
- FlagContext 维度组合
- 高风险 Flag 默认关闭
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from shared.feature_flags.flag_client import (
    FeatureFlagClient,
    FlagContext,
    get_flag_client,
    is_enabled,
    reset_flag_client,
)
from shared.feature_flags.flag_names import (
    AgentFlags,
    EdgeFlags,
    GrowthFlags,
    MemberFlags,
    OrgFlags,
    TradeFlags,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_global_client():
    """每个测试前后重置全局单例，避免测试间污染。"""
    reset_flag_client()
    yield
    reset_flag_client()


@pytest.fixture
def flags_dir(tmp_path: Path) -> Path:
    """创建临时 flags 目录，包含标准测试 Flag 定义。"""
    growth_dir = tmp_path / "growth"
    growth_dir.mkdir()

    # 增长域测试 Flags
    growth_flags = {
        "flags": [
            {
                "identifier": "growth_hub_journey_v2_enable",
                "name": "growth.hub.journey_v2.enable",
                "description": "增长中枢V2旅程",
                "defaultValue": False,
                "environments": {
                    "dev": True,
                    "test": True,
                    "uat": True,
                    "pilot": False,
                    "prod": False,
                },
                "targeting_rules": {
                    "pilot": [
                        {"dimension": "brand_id", "values": ["pilot_brand_001"]},
                    ],
                    "prod": [
                        {"dimension": "store_id", "values": ["vip_store_001"]},
                    ],
                },
            },
            {
                "identifier": "growth_agent_auto_publish_enable",
                "name": "growth.agent.suggestion.auto_publish",
                "description": "Agent建议自动发布（高风险）",
                "defaultValue": False,
                "risk_level": "HIGH",
                "environments": {
                    "dev": False,
                    "test": False,
                    "uat": False,
                    "pilot": False,
                    "prod": False,
                },
                "targeting_rules": {
                    "pilot": [
                        {"dimension": "role_code", "values": ["L3"]},
                    ],
                },
            },
            {
                "identifier": "growth_touch_frequency_control_enable",
                "name": "growth.touch.frequency_control.enable",
                "description": "触达频控",
                "defaultValue": False,
                "environments": {
                    "dev": True,
                    "test": True,
                    "uat": True,
                    "pilot": True,
                    "prod": False,
                },
                "targeting_rules": {},
            },
        ]
    }

    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()

    # Agent 域测试 Flags
    agent_flags = {
        "flags": [
            {
                "identifier": "agent_l3_autonomy_enable",
                "name": "agent.l3_autonomy.enable",
                "description": "L3全自治（最高风险）",
                "defaultValue": False,
                "risk_level": "CRITICAL",
                "environments": {
                    "dev": False,
                    "test": False,
                    "uat": False,
                    "pilot": False,
                    "prod": False,
                },
                "targeting_rules": {
                    "pilot": [
                        {"dimension": "store_id", "values": []},
                    ],
                },
            },
            {
                "identifier": "agent_trade_discount_alert_enable",
                "name": "agent.trade.discount_alert.enable",
                "description": "折扣健康预警",
                "defaultValue": False,
                "environments": {
                    "dev": True,
                    "test": True,
                    "uat": True,
                    "pilot": True,
                    "prod": False,
                },
                "targeting_rules": {
                    "prod": [
                        {"dimension": "role_code", "values": ["L1", "L2", "L3"]},
                    ],
                },
            },
        ]
    }

    (growth_dir / "growth_hub_flags.yaml").write_text(yaml.dump(growth_flags, allow_unicode=True), encoding="utf-8")
    (agents_dir / "agent_flags.yaml").write_text(yaml.dump(agent_flags, allow_unicode=True), encoding="utf-8")

    return tmp_path


@pytest.fixture
def dev_client(flags_dir: Path) -> FeatureFlagClient:
    return FeatureFlagClient(env="dev", flags_dir=str(flags_dir))


@pytest.fixture
def prod_client(flags_dir: Path) -> FeatureFlagClient:
    return FeatureFlagClient(env="prod", flags_dir=str(flags_dir))


@pytest.fixture
def pilot_client(flags_dir: Path) -> FeatureFlagClient:
    return FeatureFlagClient(env="pilot", flags_dir=str(flags_dir))


# ---------------------------------------------------------------------------
# 测试组 1：Flag 默认值（dev vs prod 环境差异）
# ---------------------------------------------------------------------------


class TestFlagDefaultValues:
    def test_journey_v2_enabled_in_dev(self, dev_client: FeatureFlagClient):
        """dev 环境下 Journey V2 应默认开启。"""
        assert dev_client.is_enabled(GrowthFlags.JOURNEY_V2) is True

    def test_journey_v2_disabled_in_prod(self, prod_client: FeatureFlagClient):
        """prod 环境下 Journey V2 应默认关闭。"""
        assert prod_client.is_enabled(GrowthFlags.JOURNEY_V2) is False

    def test_high_risk_flag_disabled_everywhere(
        self,
        dev_client: FeatureFlagClient,
        prod_client: FeatureFlagClient,
        pilot_client: FeatureFlagClient,
    ):
        """高风险 Flag（auto_publish）在所有环境下默认关闭。"""
        assert dev_client.is_enabled(GrowthFlags.AGENT_AUTO_PUBLISH) is False
        assert prod_client.is_enabled(GrowthFlags.AGENT_AUTO_PUBLISH) is False
        assert pilot_client.is_enabled(GrowthFlags.AGENT_AUTO_PUBLISH) is False

    def test_critical_risk_flag_disabled_everywhere(
        self,
        dev_client: FeatureFlagClient,
        prod_client: FeatureFlagClient,
        pilot_client: FeatureFlagClient,
    ):
        """L3 自治（CRITICAL 风险）在所有环境下默认关闭。"""
        assert dev_client.is_enabled(AgentFlags.L3_AUTONOMY) is False
        assert prod_client.is_enabled(AgentFlags.L3_AUTONOMY) is False
        assert pilot_client.is_enabled(AgentFlags.L3_AUTONOMY) is False

    def test_touch_frequency_control_enabled_in_pilot(self, pilot_client: FeatureFlagClient):
        """触达频控在 pilot 环境默认开启。"""
        assert pilot_client.is_enabled(GrowthFlags.TOUCH_FREQUENCY_CONTROL) is True


# ---------------------------------------------------------------------------
# 测试组 2：环境变量覆盖（最高优先级）
# ---------------------------------------------------------------------------


class TestEnvVarOverride:
    def test_env_var_true_overrides_yaml_false(self, prod_client: FeatureFlagClient):
        """环境变量 true 应覆盖 YAML 中的 false。"""
        with patch.dict(
            os.environ,
            {"FEATURE_GROWTH_HUB_JOURNEY_V2_ENABLE": "true"},
        ):
            assert prod_client.is_enabled(GrowthFlags.JOURNEY_V2) is True

    def test_env_var_false_overrides_yaml_true(self, dev_client: FeatureFlagClient):
        """环境变量 false 应覆盖 YAML 中的 true。"""
        with patch.dict(
            os.environ,
            {"FEATURE_GROWTH_HUB_JOURNEY_V2_ENABLE": "false"},
        ):
            assert dev_client.is_enabled(GrowthFlags.JOURNEY_V2) is False

    def test_env_var_accepts_1_as_true(self, prod_client: FeatureFlagClient):
        """环境变量值 '1' 应被识别为 true。"""
        with patch.dict(
            os.environ,
            {"FEATURE_GROWTH_HUB_JOURNEY_V2_ENABLE": "1"},
        ):
            assert prod_client.is_enabled(GrowthFlags.JOURNEY_V2) is True

    def test_env_var_accepts_yes_as_true(self, prod_client: FeatureFlagClient):
        """环境变量值 'yes' 应被识别为 true。"""
        with patch.dict(
            os.environ,
            {"FEATURE_GROWTH_HUB_JOURNEY_V2_ENABLE": "yes"},
        ):
            assert prod_client.is_enabled(GrowthFlags.JOURNEY_V2) is True

    def test_env_var_accepts_0_as_false(self, dev_client: FeatureFlagClient):
        """环境变量值 '0' 应被识别为 false。"""
        with patch.dict(
            os.environ,
            {"FEATURE_GROWTH_HUB_JOURNEY_V2_ENABLE": "0"},
        ):
            assert dev_client.is_enabled(GrowthFlags.JOURNEY_V2) is False

    def test_env_var_case_insensitive(self, prod_client: FeatureFlagClient):
        """环境变量值大小写不敏感。"""
        with patch.dict(
            os.environ,
            {"FEATURE_GROWTH_HUB_JOURNEY_V2_ENABLE": "TRUE"},
        ):
            assert prod_client.is_enabled(GrowthFlags.JOURNEY_V2) is True

    def test_env_var_dot_replaced_with_underscore(self, prod_client: FeatureFlagClient):
        """Flag 名称中的点号应替换为下划线构成环境变量名。"""
        # growth.touch.frequency_control.enable → FEATURE_GROWTH_TOUCH_FREQUENCY_CONTROL_ENABLE
        with patch.dict(
            os.environ,
            {"FEATURE_GROWTH_TOUCH_FREQUENCY_CONTROL_ENABLE": "true"},
        ):
            assert prod_client.is_enabled(GrowthFlags.TOUCH_FREQUENCY_CONTROL) is True


# ---------------------------------------------------------------------------
# 测试组 3：targeting_rules 评估
# ---------------------------------------------------------------------------


class TestTargetingRules:
    def test_brand_id_targeting_enables_flag_for_pilot_brand(self, pilot_client: FeatureFlagClient):
        """pilot_brand_001 应通过 targeting_rules 在 pilot 环境开启 Journey V2。"""
        ctx = FlagContext(brand_id="pilot_brand_001")
        assert pilot_client.is_enabled(GrowthFlags.JOURNEY_V2, ctx) is True

    def test_brand_id_targeting_keeps_flag_off_for_other_brand(self, pilot_client: FeatureFlagClient):
        """非 pilot 品牌不应通过 targeting_rules 开启 Journey V2。"""
        ctx = FlagContext(brand_id="some_other_brand")
        assert pilot_client.is_enabled(GrowthFlags.JOURNEY_V2, ctx) is False

    def test_store_id_targeting_enables_flag_in_prod(self, prod_client: FeatureFlagClient):
        """vip_store_001 应通过 targeting_rules 在 prod 环境开启 Journey V2。"""
        ctx = FlagContext(store_id="vip_store_001")
        assert prod_client.is_enabled(GrowthFlags.JOURNEY_V2, ctx) is True

    def test_store_id_targeting_keeps_flag_off_for_non_vip(self, prod_client: FeatureFlagClient):
        """普通门店不应通过 targeting_rules 在 prod 开启 Journey V2。"""
        ctx = FlagContext(store_id="normal_store_999")
        assert prod_client.is_enabled(GrowthFlags.JOURNEY_V2, ctx) is False

    def test_role_code_l3_enables_auto_publish_in_pilot(self, pilot_client: FeatureFlagClient):
        """L3 角色应在 pilot 环境通过 targeting_rules 开启 auto_publish。"""
        ctx = FlagContext(role_code="L3")
        assert pilot_client.is_enabled(GrowthFlags.AGENT_AUTO_PUBLISH, ctx) is True

    def test_role_code_l1_keeps_auto_publish_off_in_pilot(self, pilot_client: FeatureFlagClient):
        """L1 角色不应在 pilot 开启 auto_publish（高风险 Flag 仅 L3）。"""
        ctx = FlagContext(role_code="L1")
        assert pilot_client.is_enabled(GrowthFlags.AGENT_AUTO_PUBLISH, ctx) is False

    def test_empty_values_list_does_not_enable_flag(self, pilot_client: FeatureFlagClient):
        """targeting_rules 中 values 为空列表时，不应定向开启任何 context。"""
        # L3 自治 Flag 的 store_id values 为空列表，不应开启
        ctx = FlagContext(store_id="any_store_id")
        assert pilot_client.is_enabled(AgentFlags.L3_AUTONOMY, ctx) is False

    def test_targeting_rules_without_context_returns_base_value(self, pilot_client: FeatureFlagClient):
        """没有 context 时，仅返回 YAML 环境基准值（pilot 为 False）。"""
        # pilot 环境 Journey V2 基准值为 False，无 context 时直接返回 False
        assert pilot_client.is_enabled(GrowthFlags.JOURNEY_V2) is False

    def test_prod_role_code_enables_discount_alert(self, prod_client: FeatureFlagClient):
        """prod 环境 L1/L2/L3 应通过 targeting_rules 开启折扣预警。"""
        for role in ["L1", "L2", "L3"]:
            ctx = FlagContext(role_code=role)
            assert prod_client.is_enabled(AgentFlags.TRADE_DISCOUNT_ALERT, ctx) is True


# ---------------------------------------------------------------------------
# 测试组 4：未定义 Flag
# ---------------------------------------------------------------------------


class TestUndefinedFlag:
    def test_undefined_flag_returns_false(self, dev_client: FeatureFlagClient):
        """未定义的 Flag 应返回 False（fail-safe 原则）。"""
        assert dev_client.is_enabled("some.nonexistent.flag") is False

    def test_undefined_flag_with_context_returns_false(self, dev_client: FeatureFlagClient):
        """未定义的 Flag 即使带 context 也应返回 False。"""
        ctx = FlagContext(brand_id="pilot_brand_001", role_code="L3")
        assert dev_client.is_enabled("some.nonexistent.flag", ctx) is False


# ---------------------------------------------------------------------------
# 测试组 5：FlagContext 维度组合
# ---------------------------------------------------------------------------


class TestFlagContextCombinations:
    def test_context_with_all_dimensions(self, prod_client: FeatureFlagClient):
        """完整的多维度 context 不应影响基准关闭的 Flag。"""
        ctx = FlagContext(
            tenant_id="tenant_001",
            brand_id="brand_001",
            region_id="region_south",
            store_id="store_001",
            role_code="L2",
            app_version="3.0.0",
            edge_node_group="mac_mini_m4_pilot",
        )
        # Journey V2 在 prod 无匹配 targeting_rules（store 不是 vip_store_001）
        assert prod_client.is_enabled(GrowthFlags.JOURNEY_V2, ctx) is False

    def test_get_dimension_value(self):
        """FlagContext.get_dimension_value 应正确返回各维度值。"""
        ctx = FlagContext(
            tenant_id="t_001",
            brand_id="b_001",
            region_id="r_001",
            store_id="s_001",
            role_code="L3",
            app_version="3.0.0",
            edge_node_group="group_a",
        )
        assert ctx.get_dimension_value("tenant_id") == "t_001"
        assert ctx.get_dimension_value("brand_id") == "b_001"
        assert ctx.get_dimension_value("store_id") == "s_001"
        assert ctx.get_dimension_value("role_code") == "L3"
        assert ctx.get_dimension_value("edge_node_group") == "group_a"
        assert ctx.get_dimension_value("nonexistent_dim") is None

    def test_empty_context_falls_back_to_base_value(self, dev_client: FeatureFlagClient):
        """空 context（所有维度为 None）应退化为 YAML 环境基准值。"""
        empty_ctx = FlagContext()
        # dev 环境 Journey V2 基准值为 True
        assert dev_client.is_enabled(GrowthFlags.JOURNEY_V2, empty_ctx) is True

    def test_partial_context_matches_only_matching_dimension(self, pilot_client: FeatureFlagClient):
        """部分维度的 context 仅匹配包含该维度的 targeting_rules。"""
        # 只提供 brand_id，不提供 store_id
        ctx = FlagContext(brand_id="pilot_brand_001")
        # Journey V2 pilot targeting_rules 仅用 brand_id，应命中
        assert pilot_client.is_enabled(GrowthFlags.JOURNEY_V2, ctx) is True


# ---------------------------------------------------------------------------
# 测试组 6：全局单例 + 便捷函数
# ---------------------------------------------------------------------------


class TestGlobalSingleton:
    def test_get_flag_client_returns_same_instance(self, flags_dir: Path):
        """全局单例应返回同一实例。"""
        with patch.dict(
            os.environ,
            {"TUNXIANG_ENV": "dev"},
        ):
            client1 = get_flag_client()
            client2 = get_flag_client()
            assert client1 is client2

    def test_reset_creates_new_instance(self, flags_dir: Path):
        """reset 后应创建新实例。"""
        client1 = get_flag_client()
        reset_flag_client()
        client2 = get_flag_client()
        assert client1 is not client2

    def test_is_enabled_convenience_function(self, flags_dir: Path):
        """is_enabled 便捷函数应委托全局单例执行。"""
        # 通过环境变量强制开启，不依赖 YAML 路径
        with patch.dict(
            os.environ,
            {
                "FEATURE_GROWTH_HUB_JOURNEY_V2_ENABLE": "true",
                "TUNXIANG_ENV": "prod",
            },
        ):
            reset_flag_client()
            result = is_enabled(GrowthFlags.JOURNEY_V2)
            assert result is True


# ---------------------------------------------------------------------------
# 测试组 7：Flag 名称常量完整性
# ---------------------------------------------------------------------------


class TestFlagNameConstants:
    def test_growth_flags_all_defined(self):
        """GrowthFlags 所有常量都应有值。"""
        for attr in [
            "JOURNEY_V2",
            "RECALL_V2",
            "AGENT_AUTO_PUBLISH",
            "TOUCH_FREQUENCY_CONTROL",
            "CUSTOMER_360",
            "SERVICE_REPAIR",
        ]:
            val = getattr(GrowthFlags, attr)
            assert isinstance(val, str) and len(val) > 0

    def test_agent_flags_all_defined(self):
        """AgentFlags 所有常量都应有值。"""
        for attr in [
            "HR_SHIFT_SUGGEST",
            "HR_SHIFT_AUTO_EXECUTE",
            "GROWTH_DORMANT_RECALL",
            "GROWTH_MEMBER_INSIGHT",
            "OPS_DAILY_REVIEW",
            "TRADE_DISCOUNT_ALERT",
            "FINANCE_PNL_SUMMARY",
            "ORG_ATTRITION_RISK",
            "WECOM_NOTIFY",
            "L3_AUTONOMY",
        ]:
            val = getattr(AgentFlags, attr)
            assert isinstance(val, str) and len(val) > 0

    def test_flag_names_follow_naming_convention(self):
        """所有 Flag 名称应符合命名规范：domain.module.feature.action。"""
        all_flags = (
            list(vars(GrowthFlags).values())
            + list(vars(AgentFlags).values())
            + list(vars(TradeFlags).values())
            + list(vars(OrgFlags).values())
            + list(vars(MemberFlags).values())
            + list(vars(EdgeFlags).values())
        )
        string_flags = [f for f in all_flags if isinstance(f, str) and "." in f]
        for flag in string_flags:
            parts = flag.split(".")
            assert len(parts) >= 3, f"Flag '{flag}' 不符合命名规范（至少3段）"
            assert all(len(p) > 0 for p in parts), f"Flag '{flag}' 包含空段"
