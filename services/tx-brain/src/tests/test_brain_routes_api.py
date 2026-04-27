"""brain_routes API 路由层测试

覆盖端点：
  POST /api/v1/brain/discount/analyze      — 折扣守护 Agent
  POST /api/v1/brain/member/insight        — 会员洞察 Agent
  POST /api/v1/brain/dispatch/predict      — 出餐调度预测 Agent
  POST /api/v1/brain/inventory/analyze     — 库存预警 Agent
  POST /api/v1/brain/patrol/analyze        — 巡店质检 Agent
  POST /api/v1/brain/finance/audit         — 财务稽核 Agent
  POST /api/v1/brain/customer-service/handle — 智能客服 Agent
  POST /api/v1/brain/menu/optimize         — 智能排菜 Agent
  POST /api/v1/brain/crm/campaign          — 私域运营 Agent
  GET  /api/v1/brain/health                — AI服务健康检查

测试策略：
  - 全部 mock agent 方法，不调用真实 Claude API
  - 每类端点覆盖：正常路径 / APIConnectionError 降级 / 必填字段缺失 → 422
  - 使用 httpx.AsyncClient + ASGITransport（无需真实 HTTP 服务器）
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import anthropic
import pytest
from httpx import ASGITransport, AsyncClient

from ..main import app

# ─── 常量 ──────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())


# ─── Fixture ───────────────────────────────────────────────────────


@pytest.fixture
def headers() -> dict[str, str]:
    return {
        "X-Tenant-ID": TENANT_ID,
        "X-Store-ID": STORE_ID,
        "Authorization": "Bearer test-token",
    }


@pytest.fixture
async def client():
    """ASGITransport 客户端，不需要真实监听端口。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ═══════════════════════════════════════════════════════════════════
# 1. POST /api/v1/brain/discount/analyze
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_discount_analyze_success(client, headers):
    """折扣分析：Agent 正常返回 allow 决策。"""
    mock_result = {
        "decision": "allow",
        "risk_level": "low",
        "confidence": 0.92,
        "risk_factors": [],
        "constraints_check": {"margin_ok": True, "safety_ok": True, "exp_ok": True},
    }
    with patch("services.tx_brain.src.api.brain_routes.discount_guardian") as mock_agent:
        mock_agent.analyze = AsyncMock(return_value=mock_result)
        resp = await client.post(
            "/api/v1/brain/discount/analyze",
            headers=headers,
            json={
                "event": {
                    "operator_id": "E001",
                    "dish_name": "酸菜鱼",
                    "discount_rate": 0.8,
                    "amount_fen": 8800,
                },
                "history": [],
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["decision"] == "allow"


@pytest.mark.asyncio
async def test_discount_analyze_connection_error(client, headers):
    """折扣分析：Agent 抛出 APIConnectionError → 返回 ok=False + AI_CONNECTION_ERROR。"""
    with patch("services.tx_brain.src.api.brain_routes.discount_guardian") as mock_agent:
        mock_agent.analyze = AsyncMock(
            side_effect=anthropic.APIConnectionError(request=None)  # type: ignore[arg-type]
        )
        resp = await client.post(
            "/api/v1/brain/discount/analyze",
            headers=headers,
            json={"event": {"operator_id": "E001"}, "history": []},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "AI_CONNECTION_ERROR"


@pytest.mark.asyncio
async def test_discount_analyze_missing_event_field(client, headers):
    """折扣分析：缺少必填字段 event → 422 Unprocessable Entity。"""
    resp = await client.post(
        "/api/v1/brain/discount/analyze",
        headers=headers,
        json={"history": []},  # 缺少 event
    )
    assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════
# 2. POST /api/v1/brain/member/insight
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_member_insight_success(client, headers):
    """会员洞察：Agent 正常返回会员分层。"""
    mock_result = {
        "tier": "vip",
        "insights": ["高频消费者", "偏好海鲜"],
        "recommended_dishes": ["清蒸石斑鱼"],
        "action_suggestions": ["邀请加入VIP社群"],
    }
    with patch("services.tx_brain.src.api.brain_routes.member_insight") as mock_agent:
        mock_agent.analyze = AsyncMock(return_value=mock_result)
        resp = await client.post(
            "/api/v1/brain/member/insight",
            headers=headers,
            json={
                "member": {"id": "M001", "name": "张三", "total_fen": 50000},
                "orders": [{"id": "O001", "amount_fen": 10000, "items": ["清蒸石斑鱼"]}],
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["tier"] == "vip"


@pytest.mark.asyncio
async def test_member_insight_api_error(client, headers):
    """会员洞察：Agent 抛出 APIError → 返回 ok=False + AI_API_ERROR。"""
    with patch("services.tx_brain.src.api.brain_routes.member_insight") as mock_agent:
        mock_agent.analyze = AsyncMock(
            side_effect=anthropic.APIStatusError(
                message="rate limit",
                response=None,  # type: ignore[arg-type]
                body=None,
            )
        )
        resp = await client.post(
            "/api/v1/brain/member/insight",
            headers=headers,
            json={"member": {"id": "M001"}, "orders": []},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "AI_API_ERROR"


@pytest.mark.asyncio
async def test_member_insight_missing_member_field(client, headers):
    """会员洞察：缺少必填字段 member → 422。"""
    resp = await client.post(
        "/api/v1/brain/member/insight",
        headers=headers,
        json={"orders": []},  # 缺少 member
    )
    assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════
# 3. POST /api/v1/brain/dispatch/predict
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_dispatch_predict_success(client, headers):
    """出餐预测：Agent 正常返回预测时间。"""
    mock_result = {
        "estimated_minutes": 18,
        "confidence": 0.85,
        "key_bottleneck": "活鲜处理",
        "recommendations": ["优先安排活鲜区厨师"],
        "source": "claude",
    }
    with patch("services.tx_brain.src.api.brain_routes.dispatch_predictor") as mock_agent:
        mock_agent.predict = AsyncMock(return_value=mock_result)
        resp = await client.post(
            "/api/v1/brain/dispatch/predict",
            headers=headers,
            json={
                "order": {
                    "id": "O001",
                    "items": [
                        {
                            "dish_name": "清蒸石斑鱼",
                            "category": "海鲜",
                            "quantity": 1,
                            "is_live_seafood": True,
                        }
                    ],
                    "table_size": 8,
                    "created_at": "2026-04-04T12:00:00",
                },
                "kitchen_load": {
                    "pending_tasks": 5,
                    "avg_wait_minutes": 12,
                    "active_chefs": 3,
                },
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["estimated_minutes"] == 18


@pytest.mark.asyncio
async def test_dispatch_predict_connection_error(client, headers):
    """出餐预测：APIConnectionError → ok=False + AI_CONNECTION_ERROR。"""
    with patch("services.tx_brain.src.api.brain_routes.dispatch_predictor") as mock_agent:
        mock_agent.predict = AsyncMock(
            side_effect=anthropic.APIConnectionError(request=None)  # type: ignore[arg-type]
        )
        resp = await client.post(
            "/api/v1/brain/dispatch/predict",
            headers=headers,
            json={"order": {"id": "O001", "items": []}, "kitchen_load": {}},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "AI_CONNECTION_ERROR"


# ═══════════════════════════════════════════════════════════════════
# 4. POST /api/v1/brain/patrol/analyze
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_patrol_analyze_success(client, headers):
    """巡店质检：Agent 正常返回风险等级 low + auto_alert_required=False。"""
    mock_result = {
        "risk_level": "low",
        "violations": [],
        "improvement_suggestions": ["保持现有卫生标准"],
        "score_trend": "stable",
        "constraints_check": {"food_safety_ok": True, "fire_safety_ok": True},
        "auto_alert_required": False,
        "source": "claude",
    }
    with patch("services.tx_brain.src.api.brain_routes.patrol_inspector") as mock_agent:
        mock_agent.analyze = AsyncMock(return_value=mock_result)
        resp = await client.post(
            "/api/v1/brain/patrol/analyze",
            headers=headers,
            json={
                "tenant_id": TENANT_ID,
                "store_id": STORE_ID,
                "patrol_date": "2026-04-04",
                "inspector_name": "李巡检",
                "checklist_items": [
                    {
                        "category": "食品安全",
                        "item_name": "冰箱温度",
                        "result": "pass",
                        "score": 10,
                        "photo_count": 1,
                        "notes": "",
                    }
                ],
                "overall_score": 92.0,
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["risk_level"] == "low"
    assert body["data"]["auto_alert_required"] is False


@pytest.mark.asyncio
async def test_patrol_analyze_missing_required_fields(client, headers):
    """巡店质检：缺少 tenant_id / checklist_items / overall_score → 422。"""
    resp = await client.post(
        "/api/v1/brain/patrol/analyze",
        headers=headers,
        json={
            "store_id": STORE_ID,
            "patrol_date": "2026-04-04",
            "inspector_name": "李巡检",
            # 缺少 tenant_id / checklist_items / overall_score
        },
    )
    assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════
# 5. POST /api/v1/brain/finance/audit
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_finance_audit_success(client, headers):
    """财务稽核：Agent 正常返回 risk_level=low + score。"""
    mock_result = {
        "risk_level": "low",
        "score": 15.0,
        "anomalies": [],
        "audit_suggestions": ["当日财务数据正常"],
        "constraints_check": {
            "margin_ok": True,
            "void_rate_ok": True,
            "cash_diff_ok": True,
        },
        "source": "claude",
    }
    with patch("services.tx_brain.src.api.brain_routes.finance_auditor") as mock_agent:
        mock_agent.analyze = AsyncMock(return_value=mock_result)
        resp = await client.post(
            "/api/v1/brain/finance/audit",
            headers=headers,
            json={
                "tenant_id": TENANT_ID,
                "store_id": STORE_ID,
                "date": "2026-04-04",
                "revenue_fen": 100_000,
                "cost_fen": 50_000,
                "cash_actual_fen": 95_000,
                "cash_expected_fen": 95_000,
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["risk_level"] == "low"


@pytest.mark.asyncio
async def test_finance_audit_connection_error(client, headers):
    """财务稽核：APIConnectionError → ok=False。"""
    with patch("services.tx_brain.src.api.brain_routes.finance_auditor") as mock_agent:
        mock_agent.analyze = AsyncMock(
            side_effect=anthropic.APIConnectionError(request=None)  # type: ignore[arg-type]
        )
        resp = await client.post(
            "/api/v1/brain/finance/audit",
            headers=headers,
            json={
                "tenant_id": TENANT_ID,
                "store_id": STORE_ID,
                "date": "2026-04-04",
                "revenue_fen": 100_000,
                "cost_fen": 50_000,
                "cash_actual_fen": 95_000,
                "cash_expected_fen": 95_000,
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "AI_CONNECTION_ERROR"


# ═══════════════════════════════════════════════════════════════════
# 6. POST /api/v1/brain/customer-service/handle
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_customer_service_handle_success(client, headers):
    """智能客服：正常处理顾客投诉，返回 intent + response。"""
    mock_result = {
        "intent": "complaint",
        "sentiment": "negative",
        "response": "非常抱歉给您带来不好的体验，我们会立即跟进处理。",
        "action_required": True,
        "actions": [{"type": "follow_up", "priority": "high"}],
        "constraints_check": {"no_false_promise": True},
        "escalate_to_human": False,
        "source": "claude",
    }
    with patch("services.tx_brain.src.api.brain_routes.customer_service") as mock_agent:
        mock_agent.handle = AsyncMock(return_value=mock_result)
        resp = await client.post(
            "/api/v1/brain/customer-service/handle",
            headers=headers,
            json={
                "tenant_id": TENANT_ID,
                "store_id": STORE_ID,
                "channel": "wechat_mp",
                "message": "上次来吃饭等了40分钟还没上菜，太慢了！",
                "message_type": "complaint",
                "customer_tier": "vip",
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["intent"] == "complaint"
    assert body["data"]["escalate_to_human"] is False


@pytest.mark.asyncio
async def test_customer_service_missing_channel(client, headers):
    """智能客服：缺少必填字段 channel 和 message → 422。"""
    resp = await client.post(
        "/api/v1/brain/customer-service/handle",
        headers=headers,
        json={
            "tenant_id": TENANT_ID,
            "store_id": STORE_ID,
            # 缺少 channel 和 message
        },
    )
    assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════
# 7. POST /api/v1/brain/crm/campaign
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_crm_campaign_success(client, headers):
    """私域运营：正常返回微信群文案 + 约束校验通过。"""
    mock_result = {
        "campaign_name": "母亲节暖心回馈",
        "wechat_group_message": "亲爱的妈妈们，母亲节快乐！本周来店享8折优惠~",
        "moments_copy": "感恩母亲，用美食传递爱。",
        "miniapp_push_title": "母亲节专属礼遇",
        "miniapp_push_content": "为妈妈预订一桌暖心好菜",
        "coupon_suggestion": "满200减30",
        "send_time_suggestion": "母亲节前一天晚上8点",
        "constraints_check": {"discount_compliant": True},
        "source": "claude",
    }
    with patch("services.tx_brain.src.api.brain_routes.crm_operator") as mock_agent:
        mock_agent.generate_campaign = AsyncMock(return_value=mock_result)
        resp = await client.post(
            "/api/v1/brain/crm/campaign",
            headers=headers,
            json={
                "tenant_id": TENANT_ID,
                "store_id": STORE_ID,
                "brand_name": "尝在一起",
                "campaign_type": "holiday",
                "target_segment": "vip",
                "target_count": 200,
                "budget_fen": 50_000,
                "key_dishes": ["清蒸石斑鱼", "招牌烤鸭"],
                "discount_limit": 0.2,
                "special_occasion": "母亲节",
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "母亲节" in body["data"]["campaign_name"]


@pytest.mark.asyncio
async def test_crm_campaign_connection_error(client, headers):
    """私域运营：APIConnectionError → ok=False + AI_CONNECTION_ERROR。"""
    with patch("services.tx_brain.src.api.brain_routes.crm_operator") as mock_agent:
        mock_agent.generate_campaign = AsyncMock(
            side_effect=anthropic.APIConnectionError(request=None)  # type: ignore[arg-type]
        )
        resp = await client.post(
            "/api/v1/brain/crm/campaign",
            headers=headers,
            json={
                "tenant_id": TENANT_ID,
                "store_id": STORE_ID,
                "brand_name": "尝在一起",
                "campaign_type": "retention",
                "target_segment": "regular",
                "target_count": 100,
                "budget_fen": 20_000,
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "AI_CONNECTION_ERROR"


# ═══════════════════════════════════════════════════════════════════
# 8. GET /api/v1/brain/health
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_brain_health_claude_reachable(client, headers):
    """健康检查：Claude API 可达 → ok=True + claude_api=reachable。"""
    mock_msg = AsyncMock()
    mock_msg.content = [{"type": "text", "text": "pong"}]

    mock_client_instance = AsyncMock()
    mock_client_instance.messages.create = AsyncMock(return_value=mock_msg)

    with patch("anthropic.AsyncAnthropic", return_value=mock_client_instance):
        resp = await client.get("/api/v1/brain/health", headers=headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["claude_api"] == "reachable"
    # 9个 Agent 全部在线
    agents = body["data"]["agents"]
    assert len(agents) == 9
    assert all(v == "ready" for v in agents.values())


@pytest.mark.asyncio
async def test_brain_health_claude_unreachable(client, headers):
    """健康检查：Claude API 不可达 → ok=False + connection_error 状态。"""
    mock_client_instance = AsyncMock()
    mock_client_instance.messages.create = AsyncMock(
        side_effect=anthropic.APIConnectionError(request=None)  # type: ignore[arg-type]
    )

    with patch("anthropic.AsyncAnthropic", return_value=mock_client_instance):
        resp = await client.get("/api/v1/brain/health", headers=headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "connection_error" in body["data"]["claude_api"]


# ═══════════════════════════════════════════════════════════════════
# 9. POST /api/v1/brain/inventory/analyze
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_inventory_analyze_success(client, headers):
    """库存预警分析：Agent 正常返回风险食材列表及采购预算。"""
    mock_result = {
        "risk_items": [
            {
                "ingredient_name": "猪肉",
                "risk_level": "high",
                "days_remaining": 1.4,
                "suggested_purchase_qty": 15,
                "suggested_purchase_unit": "kg",
            }
        ],
        "summary": "1种高风险食材，建议立即采购",
        "total_purchase_budget_estimate_fen": 60000,
        "constraints_check": {"food_safety_ok": True},
        "source": "claude",
    }
    with patch("services.tx_brain.src.api.brain_routes.inventory_sentinel") as mock_agent:
        mock_agent.analyze = AsyncMock(return_value=mock_result)
        resp = await client.post(
            "/api/v1/brain/inventory/analyze",
            headers=headers,
            json={
                "store_id": STORE_ID,
                "tenant_id": TENANT_ID,
                "inventory": [
                    {
                        "ingredient_name": "猪肉",
                        "current_qty": 5,
                        "unit": "kg",
                        "min_qty": 10,
                        "expiry_date": "2026-04-07",
                        "unit_cost_fen": 4000,
                    }
                ],
                "sales_history": [{"ingredient_name": "猪肉", "daily_usage": 3.5}],
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]["risk_items"]) == 1
    assert body["data"]["risk_items"][0]["risk_level"] == "high"
    assert body["data"]["total_purchase_budget_estimate_fen"] == 60000


@pytest.mark.asyncio
async def test_inventory_analyze_connection_error(client, headers):
    """库存预警分析：APIConnectionError → ok=False + AI_CONNECTION_ERROR。"""
    with patch("services.tx_brain.src.api.brain_routes.inventory_sentinel") as mock_agent:
        mock_agent.analyze = AsyncMock(
            side_effect=anthropic.APIConnectionError(request=None)  # type: ignore[arg-type]
        )
        resp = await client.post(
            "/api/v1/brain/inventory/analyze",
            headers=headers,
            json={
                "store_id": STORE_ID,
                "tenant_id": TENANT_ID,
                "inventory": [
                    {
                        "ingredient_name": "猪肉",
                        "current_qty": 5,
                        "unit": "kg",
                        "min_qty": 10,
                        "expiry_date": "2026-04-07",
                        "unit_cost_fen": 4000,
                    }
                ],
                "sales_history": [],
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "AI_CONNECTION_ERROR"


@pytest.mark.asyncio
async def test_inventory_analyze_missing_required_field(client, headers):
    """库存预警分析：缺少必填字段 store_id / tenant_id / inventory → 422。"""
    resp = await client.post(
        "/api/v1/brain/inventory/analyze",
        headers=headers,
        json={
            "sales_history": [],
            # 缺少 store_id / tenant_id / inventory
        },
    )
    assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════
# 10. POST /api/v1/brain/menu/optimize
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_menu_optimize_success(client, headers):
    """智能排菜：Agent 正常返回推荐菜品排序及套餐建议。"""
    mock_result = {
        "featured_dishes": [{"dish_id": "D001", "dish_name": "红烧肉", "reason": "高毛利 + 临期食材消化"}],
        "dishes_to_promote": ["D002", "D003"],
        "dishes_to_deplete": ["D004"],
        "suggested_combos": [{"combo_name": "家庭套餐A", "dishes": ["D001", "D002"], "combo_price_fen": 18800}],
        "menu_adjustments": [{"action": "feature", "dish_id": "D001", "position": 1}],
        "constraints_check": {"margin_ok": True, "food_safety_ok": True},
        "source": "claude",
    }
    with patch("services.tx_brain.src.api.brain_routes.menu_optimizer") as mock_agent:
        mock_agent.optimize = AsyncMock(return_value=mock_result)
        resp = await client.post(
            "/api/v1/brain/menu/optimize",
            headers=headers,
            json={
                "tenant_id": TENANT_ID,
                "store_id": STORE_ID,
                "date": "2026-04-04",
                "meal_period": "lunch",
                "current_inventory": [
                    {
                        "ingredient_id": "I001",
                        "name": "五花肉",
                        "quantity": 8,
                        "unit": "kg",
                        "expiry_days": 2,
                        "cost_per_unit_fen": 3500,
                    }
                ],
                "dish_performance": [
                    {
                        "dish_id": "D001",
                        "dish_name": "红烧肉",
                        "category": "热菜",
                        "avg_daily_orders": 25,
                        "margin_rate": 0.62,
                        "prep_time_minutes": 20,
                        "is_available": True,
                    }
                ],
                "weather": "sunny",
                "day_type": "weekday",
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]["featured_dishes"]) == 1
    assert body["data"]["featured_dishes"][0]["dish_name"] == "红烧肉"
    assert body["data"]["constraints_check"]["margin_ok"] is True


@pytest.mark.asyncio
async def test_menu_optimize_connection_error(client, headers):
    """智能排菜：APIConnectionError → ok=False + AI_CONNECTION_ERROR。"""
    with patch("services.tx_brain.src.api.brain_routes.menu_optimizer") as mock_agent:
        mock_agent.optimize = AsyncMock(
            side_effect=anthropic.APIConnectionError(request=None)  # type: ignore[arg-type]
        )
        resp = await client.post(
            "/api/v1/brain/menu/optimize",
            headers=headers,
            json={
                "tenant_id": TENANT_ID,
                "store_id": STORE_ID,
                "date": "2026-04-04",
                "meal_period": "dinner",
                "dish_performance": [
                    {
                        "dish_id": "D001",
                        "dish_name": "清蒸鱼",
                        "category": "海鲜",
                        "avg_daily_orders": 10,
                        "margin_rate": 0.55,
                        "prep_time_minutes": 15,
                        "is_available": True,
                    }
                ],
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "AI_CONNECTION_ERROR"


@pytest.mark.asyncio
async def test_menu_optimize_missing_required_field(client, headers):
    """智能排菜：缺少必填字段 tenant_id / store_id / date / meal_period / dish_performance → 422。"""
    resp = await client.post(
        "/api/v1/brain/menu/optimize",
        headers=headers,
        json={
            "current_inventory": [],
            # 缺少 tenant_id / store_id / date / meal_period / dish_performance
        },
    )
    assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════
# 11. GET mv-insight 快速路径端点（Phase 3，读物化视图）
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_discount_mv_insight_success(client, headers):
    """GET /brain/discount/mv-insight 正常路径：返回 inference_layer=mv_fast_path。"""
    mock_result = {
        "inference_layer": "mv_fast_path",
        "data": {"discount_rate": 0.15, "unauthorized_count": 0},
        "risk_signal": "normal",
    }
    with patch("services.tx_brain.src.api.brain_routes.discount_guardian") as mock_agent:
        mock_agent.analyze_from_mv = AsyncMock(return_value=mock_result)
        resp = await client.get(
            "/api/v1/brain/discount/mv-insight",
            params={"tenant_id": TENANT_ID, "store_id": STORE_ID},
            headers=headers,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["inference_layer"] == "mv_fast_path"
    assert body["data"]["risk_signal"] == "normal"


@pytest.mark.asyncio
async def test_inventory_mv_insight_success(client, headers):
    """GET /brain/inventory/mv-insight 正常路径：返回 BOM 损耗数据。"""
    mock_result = {
        "inference_layer": "mv_fast_path",
        "data": {
            "total_waste_fen": 12000,
            "high_waste_ingredients": ["猪肉"],
        },
        "risk_signal": "warning",
    }
    with patch("services.tx_brain.src.api.brain_routes.inventory_sentinel") as mock_agent:
        mock_agent.analyze_from_mv = AsyncMock(return_value=mock_result)
        resp = await client.get(
            "/api/v1/brain/inventory/mv-insight",
            params={"tenant_id": TENANT_ID, "store_id": STORE_ID},
            headers=headers,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["inference_layer"] == "mv_fast_path"
    assert body["data"]["risk_signal"] == "warning"


@pytest.mark.asyncio
async def test_finance_mv_insight_success(client, headers):
    """GET /brain/finance/mv-insight 正常路径：返回 P&L 财务健康数据。"""
    mock_result = {
        "inference_layer": "mv_fast_path",
        "data": {
            "revenue_fen": 500000,
            "cost_fen": 200000,
            "gross_margin_rate": 0.60,
        },
        "risk_signal": "normal",
    }
    with patch("services.tx_brain.src.api.brain_routes.finance_auditor") as mock_agent:
        mock_agent.analyze_from_mv = AsyncMock(return_value=mock_result)
        resp = await client.get(
            "/api/v1/brain/finance/mv-insight",
            params={"tenant_id": TENANT_ID, "store_id": STORE_ID},
            headers=headers,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["inference_layer"] == "mv_fast_path"
    assert body["data"]["data"]["gross_margin_rate"] == 0.60


@pytest.mark.asyncio
async def test_member_mv_insight_success(client, headers):
    """GET /brain/member/mv-insight 正常路径：返回会员 CLV 聚合数据。"""
    mock_result = {
        "inference_layer": "mv_fast_path",
        "data": {
            "avg_clv_fen": 380000,
            "vip_count": 128,
            "churn_risk_count": 23,
        },
        "risk_signal": "normal",
    }
    with patch("services.tx_brain.src.api.brain_routes.member_insight") as mock_agent:
        mock_agent.analyze_from_mv = AsyncMock(return_value=mock_result)
        resp = await client.get(
            "/api/v1/brain/member/mv-insight",
            params={"tenant_id": TENANT_ID},
            headers=headers,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["inference_layer"] == "mv_fast_path"
    assert body["data"]["data"]["vip_count"] == 128
