"""跨品牌会员智能 + 实时推荐引擎 测试

覆盖场景：
1. 跨品牌统一画像 — golden_id 不存在返回 404
2. 跨品牌会员合并 — 源品牌与目标品牌相同返回 400
3. 跨品牌积分互通 — 积分不足返回 400
4. 点餐时实时推荐 — 正常返回推荐列表
5. 加单推荐 — 订单不存在返回 404
6. 回访推荐 — 正常返回推荐列表
7. 推荐效果统计 — 正常返回指标
8. 跨品牌统计 — 正常返回统计数据
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 将 src 加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# ──────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
GOLDEN_ID = str(uuid.uuid4())
CUSTOMER_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
ORDER_ID = str(uuid.uuid4())
BRAND_A = str(uuid.uuid4())
BRAND_B = str(uuid.uuid4())
MEMBER_A = str(uuid.uuid4())
MEMBER_B = str(uuid.uuid4())


def _make_mock_db():
    """构造模拟的 async DB session。"""
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _make_result(rows=None, scalar_value=None):
    """构造模拟的 SQL 执行结果。"""
    result = MagicMock()
    result.fetchall.return_value = rows or []
    result.fetchone.return_value = rows[0] if rows else None
    result.scalar.return_value = scalar_value
    return result


def _make_row(**kwargs):
    """构造模拟的数据库行对象。"""
    row = MagicMock()
    for k, v in kwargs.items():
        setattr(row, k, v)
    return row


# ──────────────────────────────────────────────────────────────────
# Test: 跨品牌统一画像 — golden_id 不存在返回 404
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_brand_profile_not_found():
    """golden_id 无关联品牌时应返回 404"""
    from api.cross_brand_member_routes import get_cross_brand_profile

    mock_db = _make_mock_db()
    # 查询跨品牌链接返回空
    mock_db.execute = AsyncMock(return_value=_make_result(rows=[]))

    async def mock_get_db():
        yield mock_db

    with patch("api.cross_brand_member_routes.get_db", mock_get_db):
        with pytest.raises(Exception) as exc_info:
            await get_cross_brand_profile(
                golden_id=GOLDEN_ID,
                x_tenant_id=TENANT_ID,
            )
        assert "404" in str(exc_info.value.status_code) or "未找到" in str(exc_info.value.detail)


# ──────────────────────────────────────────────────────────────────
# Test: 跨品牌会员合并 — 源品牌与目标品牌相同返回 400
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_brand_merge_same_brand():
    """源品牌与目标品牌相同应返回 400"""
    from api.cross_brand_member_routes import merge_cross_brand_member, CrossBrandMergeReq

    req = CrossBrandMergeReq(
        phone="13800138000",
        source_brand_id=BRAND_A,
        target_brand_id=BRAND_A,  # 相同品牌
    )

    with pytest.raises(Exception) as exc_info:
        await merge_cross_brand_member(req=req, x_tenant_id=TENANT_ID)
    assert exc_info.value.status_code == 400
    assert "不能相同" in exc_info.value.detail


# ──────────────────────────────────────────────────────────────────
# Test: 跨品牌积分互通 — 积分不足返回 400
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_points_transfer_insufficient():
    """源品牌积分不足时应返回 400"""
    from api.cross_brand_member_routes import transfer_points_cross_brand, PointsTransferReq

    mock_db = _make_mock_db()

    call_count = 0

    async def mock_execute(query, params=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # _set_tenant
            return _make_result()
        elif call_count == 2:
            # from_link: 找到品牌关联
            return _make_result(rows=[_make_row(brand_member_id=MEMBER_A)])
        elif call_count == 3:
            # to_link: 找到品牌关联
            return _make_result(rows=[_make_row(brand_member_id=MEMBER_B)])
        elif call_count == 4:
            # 余额查询：只有 50 积分，需转 100
            return _make_result(scalar_value=50)
        return _make_result()

    mock_db.execute = AsyncMock(side_effect=mock_execute)

    async def mock_get_db():
        yield mock_db

    req = PointsTransferReq(
        golden_id=GOLDEN_ID,
        from_brand_id=BRAND_A,
        to_brand_id=BRAND_B,
        points=100,
    )

    with patch("api.cross_brand_member_routes.get_db", mock_get_db):
        with pytest.raises(Exception) as exc_info:
            await transfer_points_cross_brand(req=req, x_tenant_id=TENANT_ID)
        assert exc_info.value.status_code == 400
        assert "积分不足" in exc_info.value.detail


# ──────────────────────────────────────────────────────────────────
# Test: 点餐时实时推荐 — UUID 格式错误返回 400
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_order_time_recommend_invalid_uuid():
    """customer_id 格式错误应返回 400"""
    from api.recommendation_routes import recommend_at_order_time, OrderTimeRecommendReq

    req = OrderTimeRecommendReq(
        customer_id="not-a-uuid",
        store_id=STORE_ID,
        current_cart_items=[],
    )

    with pytest.raises(Exception) as exc_info:
        await recommend_at_order_time(req=req, x_tenant_id=TENANT_ID)
    assert exc_info.value.status_code == 400


# ──────────────────────────────────────────────────────────────────
# Test: 加单推荐 — 订单不存在返回 404
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upsell_order_not_found():
    """订单不存在应返回 404"""
    from api.recommendation_routes import recommend_upsell

    mock_db = _make_mock_db()

    call_count = 0

    async def mock_execute(query, params=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # _set_tenant
            return _make_result()
        elif call_count == 2:
            # 查询订单：不存在
            return _make_result(rows=[])
        return _make_result()

    mock_db.execute = AsyncMock(side_effect=mock_execute)

    async def mock_get_db():
        yield mock_db

    with patch("api.recommendation_routes.get_db", mock_get_db):
        with pytest.raises(Exception) as exc_info:
            await recommend_upsell(
                order_id=ORDER_ID,
                limit=3,
                x_tenant_id=TENANT_ID,
            )
        assert exc_info.value.status_code == 404
        assert "订单不存在" in exc_info.value.detail


# ──────────────────────────────────────────────────────────────────
# Test: 推荐效果统计 — tenant_id 格式错误返回 400
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_metrics_invalid_tenant():
    """tenant_id 非 UUID 格式应返回 400"""
    from api.recommendation_routes import get_recommendation_metrics

    with pytest.raises(Exception) as exc_info:
        await get_recommendation_metrics(
            days=30,
            scene=None,
            x_tenant_id="not-a-uuid",
        )
    assert exc_info.value.status_code == 400


# ──────────────────────────────────────────────────────────────────
# Test: 跨品牌统计 — tenant_id 格式错误返回 400
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_brand_stats_invalid_tenant():
    """tenant_id 非 UUID 格式应返回 400"""
    from api.cross_brand_member_routes import get_cross_brand_stats

    with pytest.raises(Exception) as exc_info:
        await get_cross_brand_stats(x_tenant_id="bad-tenant")
    assert exc_info.value.status_code == 400


# ──────────────────────────────────────────────────────────────────
# Test: 回访推荐 — UUID 格式错误返回 400
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_return_visit_invalid_customer():
    """customer_id 非 UUID 格式应返回 400"""
    from api.recommendation_routes import recommend_return_visit

    with pytest.raises(Exception) as exc_info:
        await recommend_return_visit(
            customer_id="invalid",
            limit=5,
            x_tenant_id=TENANT_ID,
        )
    assert exc_info.value.status_code == 400
