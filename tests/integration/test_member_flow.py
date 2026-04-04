"""会员流程集成测试 — 注册 / 积分 / 等级 / 储值

使用 httpx.AsyncClient 直接调用 tx-member FastAPI app（精简版）。
大部分端点为 Mock 实现（内存存储），无需 DB Mock。

测试场景:
  1. 注册会员 → 验证会员创建
  2. 消费积分 → 积分变化
  3. 等级升级 → 权益变化
  4. 储值充值 → 余额变化
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import (
    DEFAULT_HEADERS,
    MOCK_CUSTOMER_ID,
    MOCK_STORE_ID,
    MOCK_TENANT_ID,
    assert_ok,
)

# ─── 测试用 App 构建 ──────────────────────────────────────────────────────────

from fastapi import FastAPI


def _build_member_app() -> FastAPI:
    """构建仅挂载会员核心路由的测试 app。

    tx-member 的 members.py / points_routes.py / tier_routes.py
    大多为 Mock 实现，不依赖真实 DB session。
    """
    import sys
    import os

    # 确保 tx-member/src 在 path 中（模块使用相对导入）
    member_src = os.path.join(os.path.dirname(__file__), "..", "..", "services", "tx-member", "src")
    if member_src not in sys.path:
        sys.path.insert(0, os.path.abspath(member_src))

    app = FastAPI(title="test-tx-member")

    from api.members import router as member_router
    from api.points_routes import router as points_router
    from api.tier_routes import router as tier_router

    app.include_router(member_router)
    app.include_router(points_router)
    app.include_router(tier_router)

    return app


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 会员注册
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_create_member() -> None:
    """创建新会员 → ok=True + customer_id。"""
    app = _build_member_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/member/customers",
            json={"phone": "13800138001", "display_name": "测试用户", "source": "miniapp"},
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
    data = assert_ok(resp.json())
    assert "customer_id" in data


@pytest.mark.asyncio
async def test_create_member_minimal_fields() -> None:
    """仅提供手机号 → ok=True（display_name/source 有默认值）。"""
    app = _build_member_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/member/customers",
            json={"phone": "13800138002"},
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
    assert_ok(resp.json())


@pytest.mark.asyncio
async def test_get_customer_profile() -> None:
    """获取会员 360 度画像 → ok=True。"""
    app = _build_member_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/member/customers/{MOCK_CUSTOMER_ID}",
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True


@pytest.mark.asyncio
async def test_list_customers() -> None:
    """获取会员列表 → ok=True + items + total。"""
    app = _build_member_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/member/customers?store_id={MOCK_STORE_ID}",
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
    data = assert_ok(resp.json())
    assert "items" in data
    assert "total" in data


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 积分
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_earn_points() -> None:
    """消费获得积分 → ok=True + 积分明细。"""
    app = _build_member_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/member/points/earn",
            json={"card_id": "card-001", "source": "consume", "amount": 100},
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
    data = assert_ok(resp.json())
    assert data["earned"] == 100
    assert data["source"] == "consume"


@pytest.mark.asyncio
async def test_spend_points() -> None:
    """积分消耗 → ok=True。"""
    app = _build_member_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/member/points/spend",
            json={"card_id": "card-001", "amount": 50, "purpose": "cash_offset"},
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
    data = assert_ok(resp.json())
    assert data["spent"] == 50


@pytest.mark.asyncio
async def test_earn_points_invalid_amount() -> None:
    """积分数为 0 → 422 校验错误。"""
    app = _build_member_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/member/points/earn",
            json={"card_id": "card-001", "source": "consume", "amount": 0},
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_earn_points_by_order() -> None:
    """订单支付后积分入账 → ok=True。"""
    app = _build_member_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/member/points/earn-by-order",
            json={
                "customer_id": MOCK_CUSTOMER_ID,
                "order_id": str(uuid.uuid4()),
                "amount_fen": 10000,
                "source": "order",
            },
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
    assert_ok(resp.json())


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 等级体系
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_list_tiers() -> None:
    """获取等级列表 → ok=True + 四个等级。"""
    app = _build_member_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/member/tiers",
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
    data = assert_ok(resp.json())
    # MOCK_TIERS 包含 4 个等级
    assert isinstance(data, list)
    assert len(data) >= 4


@pytest.mark.asyncio
async def test_tier_has_benefits() -> None:
    """每个等级包含权益列表。"""
    app = _build_member_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/member/tiers",
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
    tiers = assert_ok(resp.json())
    for tier in tiers:
        assert "benefits" in tier
        assert isinstance(tier["benefits"], list)
        assert "discount_rate" in tier
        assert "points_multiplier" in tier


@pytest.mark.asyncio
async def test_tier_ordering() -> None:
    """等级按 level 升序排列，min_points 递增。"""
    app = _build_member_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/member/tiers",
            headers=DEFAULT_HEADERS,
        )
    tiers = assert_ok(resp.json())
    levels = [t["level"] for t in tiers]
    assert levels == sorted(levels)
    min_points = [t["min_points"] for t in tiers]
    assert min_points == sorted(min_points)


@pytest.mark.asyncio
async def test_tier_discount_rate_range() -> None:
    """等级折扣率在合理范围 (0, 1]。"""
    app = _build_member_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/member/tiers",
            headers=DEFAULT_HEADERS,
        )
    tiers = assert_ok(resp.json())
    for tier in tiers:
        assert 0 < tier["discount_rate"] <= 1.0, f"tier {tier['name']} discount_rate out of range"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. RFM 分析
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_rfm_segments() -> None:
    """获取 RFM 分层分布 → ok=True。"""
    app = _build_member_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/member/rfm/segments?store_id={MOCK_STORE_ID}",
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
    data = assert_ok(resp.json())
    assert "segments" in data


@pytest.mark.asyncio
async def test_at_risk_customers() -> None:
    """获取流失风险客户 → ok=True。"""
    app = _build_member_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/member/rfm/at-risk?store_id={MOCK_STORE_ID}",
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
    data = assert_ok(resp.json())
    assert "customers" in data


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 营销活动
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_list_campaigns() -> None:
    """获取营销活动列表 → ok=True。"""
    app = _build_member_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/member/campaigns?store_id={MOCK_STORE_ID}",
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
    data = assert_ok(resp.json())
    assert "campaigns" in data
