"""Tier 1 测试 — voice_order Agent

按 CLAUDE.md §17 + §20 Tier 1 测试标准：
  - 用例描述基于真实餐厅场景，而不是技术边界值
  - TDD：测试先于实现

5 个核心场景（issue #257 / S2-05）：
  1. 标准点餐：'加两份锅包肉'
  2. 沽清菜：'加三文鱼' → 拒绝 + 推荐替代
  3. 模糊匹配：'那个辣的鱼' → 候选列表确认
  4. 数量异常：'加 100 份米饭' → 二次确认
  5. 决策留痕完整：所有调用产生可审计的 AgentDecisionLog

运行：
  pytest services/tx-agent/src/tests/test_voice_order_tier1.py -v
"""

from __future__ import annotations

import os
import sys

import pytest

# 与 test_budget_forecast.py 保持一致：把 src/ 加进 path
_SRC_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, _SRC_DIR)

from agents.skills.voice_order import VoiceOrderAgent  # noqa: E402

TENANT_ID = "11111111-1111-1111-1111-111111111111"
STORE_ID = "22222222-2222-2222-2222-222222222222"
TABLE_ID = "A3"


# ─── Fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def menu_items() -> list[dict]:
    """模拟门店菜单（含沽清状态、价格、毛利率）"""
    return [
        {
            "dish_id": "d-001", "name": "锅包肉",
            "price_fen": 4800, "cost_fen": 1600,  # 毛利率 66.7%
            "sold_out": False, "category": "热菜",
        },
        {
            "dish_id": "d-002", "name": "剁椒鱼头",
            "price_fen": 8800, "cost_fen": 3500,
            "sold_out": False, "category": "招牌",
        },
        {
            "dish_id": "d-003", "name": "三文鱼刺身",
            "price_fen": 12800, "cost_fen": 8000,
            "sold_out": True,  # 沽清
            "category": "刺身",
        },
        {
            "dish_id": "d-004", "name": "水煮鱼",
            "price_fen": 6800, "cost_fen": 2200,
            "sold_out": False, "category": "热菜",
        },
        {
            "dish_id": "d-005", "name": "白米饭",
            "price_fen": 200, "cost_fen": 50,
            "sold_out": False, "category": "主食",
        },
        {
            "dish_id": "d-006", "name": "白切鸡",
            "price_fen": 7800, "cost_fen": 4000,
            "sold_out": False, "category": "凉菜",
        },
    ]


@pytest.fixture
def agent() -> VoiceOrderAgent:
    return VoiceOrderAgent(tenant_id=TENANT_ID, store_id=STORE_ID)


# ─── 场景 1：标准点餐 ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_standard_order_two_guoboarou(agent, menu_items):
    """场景 1：'加两份锅包肉' — 应正常解析 + 匹配 + 准备下单"""
    # Step 1: 解析意图
    parse_result = await agent.run("parse_order_intent", {"text": "加两份锅包肉"})
    assert parse_result.success, f"解析失败: {parse_result.error}"
    intents = parse_result.data["intent"]
    assert len(intents) >= 1
    intent = intents[0]
    assert intent["action"] == "add"
    assert intent["quantity"] == 2
    assert "锅包肉" in intent["dish"]

    # Step 2: 匹配菜品
    match_result = await agent.run("match_dishes", {
        "dish": intent["dish"],
        "menu_items": menu_items,
    })
    assert match_result.success
    best = match_result.data["best_match"]
    assert best is not None
    assert best["dish_id"] == "d-001"  # 锅包肉
    assert best["score"] >= 0.85

    # Step 3: 端到端：process 一次性走完
    process_result = await agent.run("process_voice_order", {
        "text": "加两份锅包肉",
        "menu_items": menu_items,
        "table_id": TABLE_ID,
    })
    assert process_result.success
    assert process_result.constraints_passed, f"约束应通过：{process_result.constraints_detail}"
    surface = process_result.data["a2ui_surface"]
    assert surface["surfaceId"]
    # A2UI Surface 应包含 OrderConfirm 卡片 + 两个动作按钮
    assert any(c["type"] == "card" for c in surface["components"])
    actions = [c for c in surface["components"] if c["type"] == "button"]
    labels = [c["properties"]["label"] for c in actions]
    assert "确认下单" in labels or "确认" in labels
    assert "取消" in labels


# ─── 场景 2：沽清菜 ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sold_out_dish_rejected_with_alternative(agent, menu_items):
    """场景 2：'加三文鱼刺身' 已沽清 → 拒绝并推荐替代菜（食安/客户体验联动）"""
    result = await agent.run("process_voice_order", {
        "text": "加一份三文鱼刺身",
        "menu_items": menu_items,
        "table_id": TABLE_ID,
    })
    assert result.success, "Agent 本身应成功，只是返回'拒绝'状态"
    # 拒绝下单：success 是 Agent 完成调度，不代表"下单完成"
    surface = result.data["a2ui_surface"]
    # 应含警告卡片 + 替代菜品列表
    surface_text = str(surface)
    assert "沽清" in surface_text or "已售完" in surface_text or "缺货" in surface_text
    # 应推荐替代（同类菜或随机）
    alternatives = result.data.get("alternatives", [])
    assert len(alternatives) >= 1, "沽清菜应给出替代推荐"
    # 替代必须不沽清
    for alt in alternatives:
        assert not alt.get("sold_out", False)


# ─── 场景 3：模糊匹配 ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fuzzy_match_returns_candidates(agent, menu_items):
    """场景 3：'那个辣的鱼' 模糊指代 → 返回 ≥2 个候选让用户确认"""
    result = await agent.run("process_voice_order", {
        "text": "那个辣的鱼",
        "menu_items": menu_items,
        "table_id": TABLE_ID,
    })
    # 模糊场景：不直接下单，要求用户确认候选
    assert result.success
    assert result.data.get("requires_confirmation") is True or result.data.get("candidate_count", 0) > 1
    candidates = result.data.get("candidates", [])
    # 至少含 "剁椒鱼头" 和 "水煮鱼"
    candidate_names = {c["name"] for c in candidates}
    assert "剁椒鱼头" in candidate_names or "水煮鱼" in candidate_names


# ─── 场景 4：数量异常 ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_excessive_quantity_requires_manual_confirm(agent, menu_items):
    """场景 4：'加 100 份米饭' 数量异常（> 10）→ 强制二次确认（毛利保护 + 客户体验）"""
    result = await agent.run("process_voice_order", {
        "text": "加100份米饭",
        "menu_items": menu_items,
        "table_id": TABLE_ID,
    })
    assert result.success
    # 数量异常应触发显式 require_confirmation
    assert result.data.get("requires_confirmation") is True
    quantity_warnings = result.data.get("warnings", [])
    assert any(
        ("数量" in w or "份数" in w or "异常" in w) for w in quantity_warnings
    ), f"应警告数量异常，实际 warnings={quantity_warnings}"


# ─── 场景 5：决策留痕完整 ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_decision_log_complete(agent, menu_items):
    """场景 5：每次调用 .run() 产生可审计的 AgentResult，含三条硬约束校验

    关键字段：
      - reasoning（推理路径）
      - constraints_passed / constraints_detail
      - confidence
      - execution_ms
      - inference_layer (edge / cloud)
      - input/output 可序列化
    """
    result = await agent.run("process_voice_order", {
        "text": "加两份锅包肉",
        "menu_items": menu_items,
        "table_id": TABLE_ID,
    })

    # 必填决策留痕字段
    assert result.reasoning, "reasoning 必填"
    assert isinstance(result.constraints_passed, bool)
    assert isinstance(result.constraints_detail, dict)
    assert "scope" in result.constraints_detail
    assert 0 <= result.confidence <= 1.0
    assert result.execution_ms >= 0
    assert result.inference_layer in ("edge", "cloud", "edge+cloud")

    # 输入/输出可 JSON 序列化（决策日志写库前的必要条件）
    import json
    json.dumps(result.data, ensure_ascii=False)
    json.dumps(result.constraints_detail, ensure_ascii=False)


# ─── 场景 6（隐含验收）：A2UI Surface 结构合规 ─────────────────────────

@pytest.mark.asyncio
async def test_a2ui_surface_structure(agent, menu_items):
    """A2UI Surface JSON 必须符合 surfaceId + components[] 结构（v0.8 规范）"""
    result = await agent.run("process_voice_order", {
        "text": "加两份锅包肉",
        "menu_items": menu_items,
        "table_id": TABLE_ID,
    })
    surface = result.data["a2ui_surface"]
    assert "surfaceId" in surface
    assert "components" in surface
    assert isinstance(surface["components"], list)
    assert len(surface["components"]) >= 2  # 至少 1 卡片 + 1 按钮
    # 每个 component 必须有 id + type
    for c in surface["components"]:
        assert "id" in c
        assert "type" in c
        assert c["type"] in ("card", "button", "text", "list", "badge", "table", "progress", "chart")
