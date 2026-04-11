"""Agent 自治等级控制器 + ROI效果量化 集成测试

测试场景:
  1. 获取默认自治等级配置（全部L1）
  2. 升级Agent自治等级到L2/L3
  3. 自动执行规则引擎正确性
  4. ROI汇总接口（无数据时返回空结构）
  5. ROI排行榜接口
  6. Pending操作接口
  7. 未知Agent更新返回错误
"""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import (
    DEFAULT_HEADERS,
    MOCK_TENANT_ID,
    assert_ok,
    assert_err,
)

# ─── 确保 tx-agent/src 在 path 中 ──────────────────────────────────────────
_AGENT_SRC = os.path.join(os.path.dirname(__file__), "..", "..", "services", "tx-agent", "src")
if _AGENT_SRC not in sys.path:
    sys.path.insert(0, os.path.abspath(_AGENT_SRC))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  自动执行规则引擎 — 纯函数测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from api.autonomy_controller_routes import (
    AUTO_EXECUTE_RULES,
    AUTONOMY_LEVELS,
    get_auto_actions,
    is_auto_executable,
)


class TestAutoExecuteRules:
    """自动执行规则引擎测试。"""

    def test_l1_no_auto_actions(self) -> None:
        """L1等级不应有任何自动执行操作。"""
        for agent_id in AUTO_EXECUTE_RULES:
            actions = get_auto_actions(agent_id, 1)
            assert actions == [], f"{agent_id} L1 should have no auto actions, got {actions}"

    def test_l2_subset_of_l3(self) -> None:
        """L2的自动执行操作应是L3的子集。"""
        for agent_id, rules in AUTO_EXECUTE_RULES.items():
            l2 = set(rules.get("L2", []))
            l3 = set(rules.get("L3", []))
            assert l2.issubset(l3), f"{agent_id}: L2 {l2} is not subset of L3 {l3}"

    def test_discount_guardian_l2_actions(self) -> None:
        """折扣守护L2应能自动冻结可疑优惠券和通知管理者。"""
        actions = get_auto_actions("discount_guardian", 2)
        assert "freeze_suspicious_coupon" in actions
        assert "alert_manager" in actions
        assert "auto_adjust_discount_limit" not in actions

    def test_discount_guardian_l3_actions(self) -> None:
        """折扣守护L3应额外包含自动调整折扣上限。"""
        actions = get_auto_actions("discount_guardian", 3)
        assert "auto_adjust_discount_limit" in actions

    def test_is_auto_executable(self) -> None:
        """is_auto_executable 应正确判断操作是否可自动执行。"""
        assert is_auto_executable("inventory_agent", 2, "auto_soldout_sync") is True
        assert is_auto_executable("inventory_agent", 2, "auto_generate_purchase_order") is False
        assert is_auto_executable("inventory_agent", 3, "auto_generate_purchase_order") is True
        assert is_auto_executable("inventory_agent", 1, "auto_soldout_sync") is False

    def test_unknown_agent_returns_empty(self) -> None:
        """未知Agent应返回空操作列表。"""
        actions = get_auto_actions("nonexistent_agent", 3)
        assert actions == []

    def test_autonomy_levels_complete(self) -> None:
        """自治等级定义应包含L1/L2/L3。"""
        assert 1 in AUTONOMY_LEVELS
        assert 2 in AUTONOMY_LEVELS
        assert 3 in AUTONOMY_LEVELS
        assert AUTONOMY_LEVELS[1]["label"] == "L1"
        assert AUTONOMY_LEVELS[3]["label"] == "L3"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ROI 定义完整性测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from api.agent_roi_routes import AGENT_ROI_DEFINITIONS


class TestAgentROIDefinitions:
    """Agent ROI 指标定义完整性测试。"""

    def test_all_core_agents_have_roi_definitions(self) -> None:
        """9个核心Agent都应有ROI指标定义。"""
        expected_agents = {
            "discount_guardian", "inventory_agent", "scheduling_agent",
            "member_insight", "smart_menu", "serve_dispatch",
            "finance_audit", "store_inspect", "private_ops",
        }
        defined = set(AGENT_ROI_DEFINITIONS.keys())
        assert expected_agents == defined, f"Missing: {expected_agents - defined}, Extra: {defined - expected_agents}"

    def test_each_agent_has_at_least_one_metric(self) -> None:
        """每个Agent至少定义一个指标。"""
        for agent_id, defn in AGENT_ROI_DEFINITIONS.items():
            assert len(defn["metrics"]) > 0, f"{agent_id} has no metrics defined"

    def test_metric_has_required_fields(self) -> None:
        """每个指标应包含 type/label/unit/direction 字段。"""
        for agent_id, defn in AGENT_ROI_DEFINITIONS.items():
            for metric in defn["metrics"]:
                assert "type" in metric, f"{agent_id} metric missing 'type'"
                assert "label" in metric, f"{agent_id} metric missing 'label'"
                assert "unit" in metric, f"{agent_id} metric missing 'unit'"
                assert "direction" in metric, f"{agent_id} metric missing 'direction'"
                assert metric["direction"] in ("higher_better", "lower_better"), \
                    f"{agent_id} metric direction invalid: {metric['direction']}"

    def test_financial_metrics_use_fen(self) -> None:
        """金额类指标应以 _fen 结尾，单位为'分'。"""
        for agent_id, defn in AGENT_ROI_DEFINITIONS.items():
            for metric in defn["metrics"]:
                if metric["unit"] == "分":
                    assert metric["type"].endswith("_fen"), \
                        f"{agent_id}.{metric['type']}: unit=分 but type doesn't end with _fen"
