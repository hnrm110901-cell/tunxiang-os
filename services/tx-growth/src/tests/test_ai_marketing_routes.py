"""AI营销自动化路由测试（tx-growth）

覆盖：
  1. campaign-brief 返回内容包 + 受众 + 渠道计划
  2. auto-journey 路由到正确的 Agent action
  3. performance-summary 返回必要字段
  4. channel-test mock 模式连通性验证
  5. 未知触发事件返回 422
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 使用独立 FastAPI app 测试路由
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ..api.ai_marketing_routes import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

TENANT_HEADERS = {"X-Tenant-ID": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}


# ─────────────────────────────────────────────────────────────────────────────
# 辅助：mock DB session 依赖
# ─────────────────────────────────────────────────────────────────────────────


def _override_db():
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()

    async def _gen():
        yield mock_session

    return _gen


# ─────────────────────────────────────────────────────────────────────────────
# 测试 1: campaign-brief 返回内容包 + 受众 + 渠道计划
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_campaign_brief_returns_content_package() -> None:
    """提交活动简报，返回 brief_id + 内容包 + 受众 + 渠道计划 + ROI预测"""
    mock_brain_response = {
        "ok": True,
        "data": {
            "request_id": "req-001",
            "campaign_type": "new_dish_launch",
            "contents": [{"channel": "sms", "body": "新品上市！"}],
            "cached": False,
        },
    }

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_brain_response
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        # Mock DB session
        with patch("services.tx_growth.src.api.ai_marketing_routes._get_db", _override_db()):
            response = client.post(
                "/api/v1/growth/ai-marketing/campaign-brief",
                headers=TENANT_HEADERS,
                json={
                    "campaign_type": "new_dish_launch",
                    "brand_voice": {"brand_name": "测试品牌", "tone": "活泼年轻"},
                    "store_id": "store-001",
                    "target_channels": ["sms", "wechat_subscribe"],
                },
            )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "brief_id" in data["data"]
    assert "content_package" in data["data"]
    assert "recommended_audience" in data["data"]
    assert "channel_plan" in data["data"]
    assert "roi_forecast" in data["data"]


# ─────────────────────────────────────────────────────────────────────────────
# 测试 2: auto-journey 路由到正确 Agent action
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_journey_routes_to_correct_action() -> None:
    """post_order 事件 → execute_post_order_touch action"""
    mock_agent_response = {
        "ok": True,
        "data": {
            "action": "execute_post_order_touch",
            "reasoning": "感谢消息已发送",
            "confidence": 0.92,
        },
    }

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_agent_response
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        response = client.post(
            "/api/v1/growth/ai-marketing/auto-journey",
            headers=TENANT_HEADERS,
            json={
                "trigger_event": "post_order",
                "member_id": "mbr-001",
                "store_id": "store-001",
                "event_payload": {"order_id": "ord-001", "order_amount_fen": 8800},
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["data"]["trigger_event"] == "post_order"


# ─────────────────────────────────────────────────────────────────────────────
# 测试 3: 未知触发事件返回 422
# ─────────────────────────────────────────────────────────────────────────────


def test_unknown_trigger_event_returns_422() -> None:
    """未知 trigger_event 应返回 422 Unprocessable Entity"""
    response = client.post(
        "/api/v1/growth/ai-marketing/auto-journey",
        headers=TENANT_HEADERS,
        json={
            "trigger_event": "unknown_event_xyz",
            "member_id": "mbr-001",
            "store_id": "store-001",
        },
    )
    assert response.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# 测试 4: performance-summary 包含必要字段
# ─────────────────────────────────────────────────────────────────────────────


def test_performance_summary_format() -> None:
    """营销效果报告包含必要字段"""
    with patch("services.tx_growth.src.api.ai_marketing_routes._get_db", _override_db()):
        response = client.get(
            "/api/v1/growth/ai-marketing/performance-summary",
            headers=TENANT_HEADERS,
            params={"store_id": "store-001", "days": 7},
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert "total_touches" in data
    assert "channel_breakdown" in data
    assert "campaign_performance" in data
    assert "overall_roi" in data
    assert data["overall_roi"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# 测试 5: channel-test mock 模式
# ─────────────────────────────────────────────────────────────────────────────


def test_channel_test_mock_mode() -> None:
    """渠道连通性测试在 mock 模式下正常运行（无需真实凭据）"""
    response = client.post(
        "/api/v1/growth/ai-marketing/channel-test",
        headers=TENANT_HEADERS,
        json={"channels": ["sms", "wechat_subscribe", "meituan", "douyin"]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["data"]["channels_tested"] == 4
    results = data["data"]["results"]
    # 在 mock 模式下，每个渠道应返回 mock_mode 状态
    for ch in ["sms", "wechat_subscribe", "meituan", "douyin"]:
        assert ch in results


# ─────────────────────────────────────────────────────────────────────────────
# 测试 6: campaign-brief ContentHub 不可用时降级
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_campaign_brief_fallback_when_brain_unavailable() -> None:
    """ContentHub 不可用时，使用降级内容，brief 仍然返回 200"""
    import httpx

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        mock_client_cls.return_value = mock_client

        with patch("services.tx_growth.src.api.ai_marketing_routes._get_db", _override_db()):
            response = client.post(
                "/api/v1/growth/ai-marketing/campaign-brief",
                headers=TENANT_HEADERS,
                json={
                    "campaign_type": "daily_special",
                    "brand_voice": {"brand_name": "测试品牌", "tone": "亲切"},
                    "store_id": "store-001",
                },
            )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    # 降级内容存在
    assert "content_package" in data["data"]
    assert data["data"]["content_package"].get("fallback") is True
