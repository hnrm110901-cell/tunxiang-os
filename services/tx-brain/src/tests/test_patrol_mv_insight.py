"""patrol/mv-insight POST 端点测试

覆盖端点：
  POST /api/v1/brain/patrol/mv-insight  — 巡店质检增强分析（mv_public_opinion背景注入）

测试策略：
  - 全部 mock patrol_inspector.analyze_from_mv，不调用真实 Claude API 或数据库
  - override get_db_no_rls 依赖，注入 AsyncMock db session
  - 覆盖：正常路径 / 舆情数据注入验证 / APIConnectionError 降级 / 必填字段缺失 → 422
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import anthropic
import pytest
from httpx import ASGITransport, AsyncClient

from ..main import app
from shared.ontology.src.database import get_db_no_rls

# ─── 常量 ──────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())

# ─── 标准巡检 payload ───────────────────────────────────────────────

PATROL_PAYLOAD = {
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
    "overall_score": 88.0,
}

# ─── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def headers() -> dict[str, str]:
    return {
        "X-Tenant-ID": TENANT_ID,
        "X-Store-ID": STORE_ID,
        "Authorization": "Bearer test-token",
    }


@pytest.fixture
def mock_db():
    """返回一个 AsyncMock db session，用于 override get_db_no_rls 依赖。"""
    return AsyncMock()


@pytest.fixture
async def client(mock_db):
    """ASGITransport 客户端，override get_db_no_rls 依赖注入 mock db。"""
    async def _override_get_db_no_rls():
        yield mock_db

    app.dependency_overrides[get_db_no_rls] = _override_get_db_no_rls
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════════
# 1. 正常路径：analyze_from_mv 返回增强分析结果
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_patrol_mv_insight_success(client, headers):
    """巡店质检增强分析：analyze_from_mv 正常返回，inference_layer=mv_fast_path_enhanced。"""
    mock_result = {
        "inference_layer": "mv_fast_path_enhanced",
        "risk_level": "low",
        "violations": [],
        "improvement_suggestions": ["保持现有卫生标准"],
        "score_trend": "stable",
        "constraints_check": {"food_safety_ok": True, "fire_safety_ok": True},
        "auto_alert_required": False,
        "source": "claude",
    }
    with patch(
        "services.tx_brain.src.api.brain_routes.patrol_inspector"
    ) as mock_agent:
        mock_agent.analyze_from_mv = AsyncMock(return_value=mock_result)
        resp = await client.post(
            "/api/v1/brain/patrol/mv-insight",
            headers=headers,
            json=PATROL_PAYLOAD,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["inference_layer"] == "mv_fast_path_enhanced"
    assert body["data"]["risk_level"] == "low"
    assert body["data"]["auto_alert_required"] is False


# ═══════════════════════════════════════════════════════════════════
# 2. 舆情数据注入验证：返回结果包含 public_opinion 字段
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_patrol_mv_insight_with_opinion_context(client, headers):
    """巡店质检增强分析：返回结果包含 public_opinion 字段，验证舆情数据已注入分析背景。"""
    mock_result = {
        "inference_layer": "mv_fast_path_enhanced",
        "risk_level": "medium",
        "violations": [{"category": "服务质量", "item": "等待时间过长"}],
        "improvement_suggestions": ["优化出餐流程", "增配服务人员"],
        "score_trend": "declining",
        "constraints_check": {"food_safety_ok": True, "fire_safety_ok": True},
        "auto_alert_required": False,
        "public_opinion": {
            "total_negative": 12,
            "worst_platform": "美团",
            "avg_sentiment": 0.42,
            "platform_breakdown": [
                {"platform": "美团", "total": 80, "negative": 8, "avg_sentiment": 0.38},
                {"platform": "大众点评", "total": 50, "negative": 4, "avg_sentiment": 0.48},
            ],
        },
        "source": "claude",
    }
    with patch(
        "services.tx_brain.src.api.brain_routes.patrol_inspector"
    ) as mock_agent:
        mock_agent.analyze_from_mv = AsyncMock(return_value=mock_result)
        resp = await client.post(
            "/api/v1/brain/patrol/mv-insight",
            headers=headers,
            json=PATROL_PAYLOAD,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    # 验证舆情数据被正确注入并反映在结果中
    opinion = body["data"]["public_opinion"]
    assert opinion["total_negative"] == 12
    assert opinion["worst_platform"] == "美团"
    assert opinion["avg_sentiment"] == 0.42
    assert len(opinion["platform_breakdown"]) == 2


# ═══════════════════════════════════════════════════════════════════
# 3. APIConnectionError 降级：ok=False + code=AI_CONNECTION_ERROR
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_patrol_mv_insight_connection_error(client, headers):
    """巡店质检增强分析：analyze_from_mv 抛出 APIConnectionError → ok=False + AI_CONNECTION_ERROR。"""
    with patch(
        "services.tx_brain.src.api.brain_routes.patrol_inspector"
    ) as mock_agent:
        mock_agent.analyze_from_mv = AsyncMock(
            side_effect=anthropic.APIConnectionError(request=None)  # type: ignore[arg-type]
        )
        resp = await client.post(
            "/api/v1/brain/patrol/mv-insight",
            headers=headers,
            json=PATROL_PAYLOAD,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "AI_CONNECTION_ERROR"
    assert "Claude API" in body["error"]["message"]


# ═══════════════════════════════════════════════════════════════════
# 4. 缺少必要字段 → 422 Unprocessable Entity
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_patrol_mv_insight_missing_required_field(client, headers):
    """巡店质检增强分析：缺少必填字段 tenant_id / checklist_items / overall_score → 422。"""
    resp = await client.post(
        "/api/v1/brain/patrol/mv-insight",
        headers=headers,
        json={
            "store_id": STORE_ID,
            "patrol_date": "2026-04-04",
            "inspector_name": "李巡检",
            # 缺少 tenant_id / checklist_items / overall_score
        },
    )
    assert resp.status_code == 422
