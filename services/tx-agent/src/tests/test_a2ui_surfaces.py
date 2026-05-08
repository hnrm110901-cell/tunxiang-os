"""Sprint 3 S3-03 — A2UI Surface 生成器单测

验证三个 Surface 生成器输出 JSON 符合 A2UI v0.8 协议：
  - 折扣守护 critical alert
  - 会员洞察 recommendation
  - 库存预警 warning

每个生成器至少 3 个用例（正常/边界/异常）。
所有 surface 必须可被 web-pos A2UIRenderer 安全渲染（白名单 type）。
"""
from __future__ import annotations

import sys
from pathlib import Path

# tx-agent src 路径
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agents.a2ui_surfaces import (  # noqa: E402
    build_discount_alert_surface,
    build_inventory_warning_surface,
    build_member_recommendation_surface,
)


# A2UI v0.8 已上线的白名单 type（与 web-pos types.ts 保持同步）
A2UI_WHITELIST_TYPES = {
    "card", "text", "button", "list", "input", "image", "chart", "badge",
    "progress", "table", "actions", "section", "divider", "spinner",
    # Sprint 3 S3-01 新增
    "form", "map", "heatmap", "timeline", "cascader", "tabs",
}


def _walk_node_types(node: dict) -> set[str]:
    """递归收集 surface 树中所有 type"""
    types = {node.get("type", "")}
    for child in node.get("children", []) or []:
        types |= _walk_node_types(child)
    return types


def _assert_surface_shape(surface: dict, expected_agent_id: str):
    """通用 shape 断言"""
    assert "surfaceId" in surface
    assert surface["version"] == "0.8"
    assert "surface" in surface
    assert "metadata" in surface
    assert surface["metadata"]["agentId"] == expected_agent_id
    assert 0.0 <= surface["metadata"]["confidence"] <= 1.0
    # 所有 type 必须在白名单中
    types = _walk_node_types(surface["surface"])
    types -= {""}
    assert types <= A2UI_WHITELIST_TYPES, f"非白名单 type: {types - A2UI_WHITELIST_TYPES}"


# ─── 1. 折扣守护 ───────────────────────────────────────────

class TestDiscountAlertSurface:
    def test_critical_breach_basic(self):
        """正常：折扣率 35%，折后毛利 -200，底线 500，差额 700 分"""
        s = build_discount_alert_surface(
            order_id="O-XJ-2026050810001",
            discount_rate=0.35,
            margin_after_discount_fen=-200,
            margin_threshold_fen=500,
            operator_id="cashier-001",
        )
        _assert_surface_shape(s, expected_agent_id="discount_guard")
        assert s["surface"]["props"]["severity"] == "critical"
        assert "O-XJ-2026050810001" in s["surface"]["props"]["subtitle"]

    def test_actions_payload_includes_order_id(self):
        """approve/reject 按钮的 actionPayload 必须含 order_id（决策留痕前提）"""
        s = build_discount_alert_surface(
            order_id="O-1",
            discount_rate=0.4,
            margin_after_discount_fen=0,
            margin_threshold_fen=1000,
            operator_id="op-1",
        )
        actions_node = next(
            c for c in s["surface"]["children"] if c["type"] == "actions"
        )
        buttons = actions_node["props"]["buttons"]
        assert len(buttons) == 2
        for btn in buttons:
            assert btn["actionPayload"]["order_id"] == "O-1"

    def test_no_operator_id_still_works(self):
        """边界：operator_id 缺失时仍能渲染（不抛错）"""
        s = build_discount_alert_surface(
            order_id="O-2",
            discount_rate=0.5,
            margin_after_discount_fen=-1000,
            margin_threshold_fen=500,
            operator_id=None,
        )
        _assert_surface_shape(s, expected_agent_id="discount_guard")


# ─── 2. 会员洞察 ───────────────────────────────────────────

class TestMemberRecommendationSurface:
    def test_diamond_member_basic(self):
        """钻石会员到店，3 个偏好 + 2 个推荐操作"""
        s = build_member_recommendation_surface(
            member_id="M-00412",
            member_name="王总",
            member_level="钻石",
            last_visit_days=16,
            preferences=["靠窗位", "少辣", "清蒸系"],
            recommendations=[
                {"label": "推荐霸王蟹", "action": "menu.recommend",
                 "payload": {"dish_id": "dish-001"}},
                {"label": "升舱包间", "action": "table.upgrade", "variant": "primary"},
            ],
        )
        _assert_surface_shape(s, expected_agent_id="member_insight")
        assert "钻石会员" in s["surface"]["props"]["title"]

    def test_recommendation_payload_includes_member_id(self):
        """所有推荐按钮的 actionPayload 必须自动注入 member_id"""
        s = build_member_recommendation_surface(
            member_id="M-001",
            member_name="测试",
            member_level="金",
            last_visit_days=3,
            preferences=[],
            recommendations=[
                {"label": "A", "action": "x", "payload": {"k": "v"}},
                {"label": "B", "action": "y"},  # 无 payload
            ],
        )
        actions_node = next(
            c for c in s["surface"]["children"] if c["type"] == "actions"
        )
        for btn in actions_node["props"]["buttons"]:
            assert btn["actionPayload"]["member_id"] == "M-001"
        # 第一个保留原 payload 的 k
        assert actions_node["props"]["buttons"][0]["actionPayload"]["k"] == "v"

    def test_empty_preferences_renders_empty_list(self):
        """边界：偏好空列表时仍正常渲染"""
        s = build_member_recommendation_surface(
            member_id="M-002",
            member_name="新会员",
            member_level="普通",
            last_visit_days=0,
            preferences=[],
            recommendations=[],
        )
        _assert_surface_shape(s, expected_agent_id="member_insight")


# ─── 3. 库存预警 ───────────────────────────────────────────

class TestInventoryWarningSurface:
    def test_warning_overall_severity(self):
        """所有 item 都是 warning 时整体 severity=warning"""
        s = build_inventory_warning_surface(
            items=[
                {"name": "霸王蟹", "remaining_qty": 8, "unit": "只",
                 "expiry_minutes": 30, "severity": "warning"},
                {"name": "石斑鱼", "remaining_qty": 3, "unit": "条",
                 "expiry_minutes": 45, "severity": "warning"},
            ],
        )
        _assert_surface_shape(s, expected_agent_id="inventory_alert")
        assert s["surface"]["props"]["severity"] == "warning"

    def test_critical_item_escalates_overall(self):
        """任一 item 是 critical 时整体升级为 critical"""
        s = build_inventory_warning_surface(
            items=[
                {"name": "霸王蟹", "remaining_qty": 8, "severity": "warning"},
                {"name": "鲍鱼", "remaining_qty": 0, "severity": "critical"},
            ],
        )
        assert s["surface"]["props"]["severity"] == "critical"

    def test_table_columns_and_rows(self):
        """table 节点正确含 3 列 + 行数 = items 数"""
        items = [
            {"name": f"食材{i}", "remaining_qty": i, "unit": "份",
             "expiry_minutes": i * 10, "severity": "warning"}
            for i in range(1, 4)
        ]
        s = build_inventory_warning_surface(items=items)
        table_node = next(
            c for c in s["surface"]["children"] if c["type"] == "table"
        )
        assert len(table_node["props"]["columns"]) == 3
        assert len(table_node["props"]["rows"]) == 3
        assert table_node["props"]["rows"][0]["name"] == "食材1"

    def test_action_payload_lists_all_items(self):
        """补货按钮 payload 含所有 item names（一键补货前提）"""
        s = build_inventory_warning_surface(
            items=[
                {"name": "A", "severity": "warning"},
                {"name": "B", "severity": "warning"},
                {"name": "C", "severity": "warning"},
            ],
        )
        actions_node = next(
            c for c in s["surface"]["children"] if c["type"] == "actions"
        )
        order_btn = next(
            b for b in actions_node["props"]["buttons"] if b["action"] == "inventory.order_now"
        )
        assert order_btn["actionPayload"]["items"] == ["A", "B", "C"]
