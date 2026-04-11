"""AI营销编排 Agent 测试套件

覆盖 AiMarketingOrchestratorAgent 核心场景：
  1. 下单后触达（正常路径）
  2. 冷却期跳过
  3. 毛利底线阻断深度折扣
  4. 新客欢迎旅程
  5. 沉默用户唤醒
  6. 营销健康评分
  7. 流失拯救（降低优惠力度重试）
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ..agents.skills.ai_marketing_orchestrator import (
    AiMarketingOrchestratorAgent,
    MARKETING_COOLDOWN_RULES,
    _fallback_content,
)


# ─────────────────────────────────────────────────────────────────────────────
# fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def agent() -> AiMarketingOrchestratorAgent:
    return AiMarketingOrchestratorAgent(
        tenant_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        store_id="store-001",
    )


def _default_brand_voice() -> dict[str, Any]:
    return {"brand_name": "测试餐厅", "tone": "亲切温暖", "emoji_style": "light"}


# ─────────────────────────────────────────────────────────────────────────────
# 测试 1: 下单后触达 — 正常路径
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_order_touch_success(agent: AiMarketingOrchestratorAgent) -> None:
    """ORDER.PAID 触发：成功发送感谢消息"""
    mock_content = {
        "campaign_type": "post_order_thanks",
        "contents": [{"channel": "wechat_subscribe", "body": "感谢您的消费！"}],
    }
    mock_send = {"touch_id": "touch_001", "status": "sent"}

    with (
        patch.object(agent, "_generate_content", AsyncMock(return_value=mock_content)),
        patch.object(agent, "_dispatch_message", AsyncMock(return_value=mock_send)),
    ):
        result = await agent.execute(
            "execute_post_order_touch",
            {
                "member_id": "mbr-001",
                "order_id": "ord-001",
                "order_amount_fen": 8800,
                "store_name": "测试餐厅长沙店",
                "brand_voice": _default_brand_voice(),
            },
        )

    assert result.success is True
    assert result.constraints_passed is True
    assert result.data["order_id"] == "ord-001"
    assert result.data["send_result"]["status"] == "sent"
    assert result.confidence > 0.8


# ─────────────────────────────────────────────────────────────────────────────
# 测试 2: 冷却期内跳过触达
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cooldown_respected(agent: AiMarketingOrchestratorAgent) -> None:
    """冷却期内不触达，返回 skipped=True"""
    with patch.object(
        agent,
        "_check_cooldown",
        AsyncMock(return_value={"ok": False, "reason": "冷却期内（48h）：距上次触达仅12h"}),
    ):
        result = await agent.execute(
            "execute_post_order_touch",
            {"member_id": "mbr-002", "order_id": "ord-002", "brand_voice": _default_brand_voice()},
        )

    assert result.success is True  # 跳过不算失败
    assert result.data.get("skipped") is True
    assert "冷却期" in result.data.get("reason", "")


# ─────────────────────────────────────────────────────────────────────────────
# 测试 3: 毛利底线阻断深度折扣
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_margin_constraint_blocks_deep_discount(agent: AiMarketingOrchestratorAgent) -> None:
    """折扣超过毛利底线时，Agent 拒绝执行"""
    # 40000分均单 × 85% = 34000分，折扣38000分 > 上限 → 违反约束
    result = await agent.execute(
        "execute_winback_journey",
        {
            "member_id": "mbr-003",
            "days_inactive": 60,
            "rfm_tier": "D",
            "winback_offer_fen": 38000,  # 380元折扣远超上限
            "brand_voice": _default_brand_voice(),
        },
    )

    assert result.success is False
    assert result.constraints_passed is False
    assert len(result.constraints_detail.get("violations", [])) > 0
    assert "毛利" in result.constraints_detail["violations"][0]


# ─────────────────────────────────────────────────────────────────────────────
# 测试 4: 新客欢迎旅程
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_welcome_journey_new_member(agent: AiMarketingOrchestratorAgent) -> None:
    """新客首单后触发欢迎旅程"""
    mock_content = {"campaign_type": "new_customer_welcome", "contents": []}
    mock_send = {"touch_id": "touch_003", "status": "sent"}

    with (
        patch.object(agent, "_generate_content", AsyncMock(return_value=mock_content)),
        patch.object(agent, "_dispatch_message", AsyncMock(return_value=mock_send)),
    ):
        result = await agent.execute(
            "execute_welcome_journey",
            {
                "member_id": "mbr-004",
                "store_name": "测试餐厅",
                "welcome_offer_fen": 1000,  # 10元券，在毛利底线内
                "brand_voice": _default_brand_voice(),
            },
        )

    assert result.success is True
    assert result.constraints_passed is True
    assert "欢迎" in result.reasoning


# ─────────────────────────────────────────────────────────────────────────────
# 测试 5: 沉默用户唤醒 — 30天未到店
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_winback_journey_silent_member(agent: AiMarketingOrchestratorAgent) -> None:
    """30天沉默会员唤醒"""
    mock_content = {"campaign_type": "member_win_back", "contents": []}
    mock_send = {"touch_id": "touch_004", "status": "sent"}

    with (
        patch.object(agent, "_generate_content", AsyncMock(return_value=mock_content)),
        patch.object(agent, "_dispatch_message", AsyncMock(return_value=mock_send)),
    ):
        result = await agent.execute(
            "execute_winback_journey",
            {
                "member_id": "mbr-005",
                "days_inactive": 30,
                "rfm_tier": "C",
                "winback_offer_fen": 1500,  # 15元券，合规
                "brand_voice": _default_brand_voice(),
            },
        )

    assert result.success is True
    assert result.data["days_inactive"] == 30
    assert "30" in result.reasoning


# ─────────────────────────────────────────────────────────────────────────────
# 测试 6: 营销健康评分
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_marketing_health_score(agent: AiMarketingOrchestratorAgent) -> None:
    """营销健康评分返回合法的0-100分值"""
    result = await agent.execute(
        "get_marketing_health_score",
        {
            "store_id": "store-001",
            "channel_count": 4,
            "monthly_touches_per_member": 3.0,
            "avg_open_rate": 0.12,
            "attributed_order_pct": 0.35,
        },
    )

    assert result.success is True
    score = result.data["total_score"]
    assert 0 <= score <= 100
    assert result.data["grade"] in ("A", "B", "C", "D")
    assert "breakdown" in result.data
    assert len(result.data["suggestions"]) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# 测试 7: 不支持的 action 返回 failure
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unsupported_action(agent: AiMarketingOrchestratorAgent) -> None:
    """未知 action 应返回 success=False，不抛异常"""
    result = await agent.execute("this_action_does_not_exist", {})
    assert result.success is False
    assert "不支持" in (result.error or "")


# ─────────────────────────────────────────────────────────────────────────────
# 测试 8: 降级内容生成
# ─────────────────────────────────────────────────────────────────────────────

def test_fallback_content_structure() -> None:
    """ContentHub 不可用时降级内容格式正确"""
    pkg = _fallback_content(
        campaign_type="birthday_care",
        channels=["sms", "wechat_subscribe"],
        store_context={"store_name": "测试餐厅"},
        offer_detail={"discount_fen": 2000},
    )
    assert "contents" in pkg
    assert pkg["fallback"] is True
    assert len(pkg["contents"]) == 2
    for item in pkg["contents"]:
        assert "channel" in item
        assert "body" in item
        assert len(item["body"]) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 测试 9: 冷却规则配置完整
# ─────────────────────────────────────────────────────────────────────────────

def test_cooldown_rules_completeness() -> None:
    """所有触发场景都有对应的冷却规则"""
    expected_actions = [
        "post_order_touch", "welcome_journey", "winback_journey",
        "birthday_care", "holiday_campaign", "upgrade_celebration", "churn_rescue",
    ]
    for action in expected_actions:
        assert action in MARKETING_COOLDOWN_RULES, f"冷却规则缺少 {action}"
        assert isinstance(MARKETING_COOLDOWN_RULES[action], int)
        assert MARKETING_COOLDOWN_RULES[action] >= 0
