"""coupon_service (tx-growth) — WP-1.2 商品券配置 单元测试

覆盖：
  1. create_coupon — 正常创建、无效类型、微信同步失败
  2. list_coupons — 空列表、按类型过滤、分页
  3. get_coupon — 存在/不存在
  4. toggle_active — 启用/停用
"""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.coupon_service import ProductCouponService, get_product_coupon_service

_TENANT_ID = str(uuid.uuid4())
_COUPON_ID = str(uuid.uuid4())


@pytest.fixture
def svc():
    return ProductCouponService()


@pytest.fixture
def mock_db():
    return AsyncMock()


def _mock_mappings(rows=None, one_or_none=None):
    """Create a mock for .mappings() chaining.

    SQLAlchemy: result.mappings() → MappingResult (sync) with .one_or_none() (sync), .fetchall() and iteration.
    """
    m = MagicMock()
    m.one_or_none = MagicMock(return_value=one_or_none)
    m.__iter__ = MagicMock(return_value=iter(rows or []))
    m.fetchall = MagicMock(return_value=rows or [])
    return m


def _mock_result(scalar_value=0, mappings_rows=None, one_or_none=None):
    """Create an AsyncMock that mimics SQLAlchemy AsyncResult."""
    r = AsyncMock()
    r.scalar = MagicMock(return_value=scalar_value)
    r.mappings = MagicMock(return_value=_mock_mappings(rows=mappings_rows, one_or_none=one_or_none))
    r.fetchall = MagicMock(return_value=[])
    return r


class TestCreateCoupon:
    async def test_create_cash_coupon(self, svc, mock_db):
        mock_db.execute = AsyncMock(return_value=MagicMock())
        result = await svc.create_coupon(
            tenant_id=_TENANT_ID, name="测试代金券", coupon_type="cash",
            db=mock_db, cash_amount_fen=1000, total_quantity=500, wechat_sync=False,
        )
        assert result["name"] == "测试代金券"
        assert result["coupon_type"] == "cash"
        assert result["wechat_activity_id"] is None
        assert uuid.UUID(result["id"])

    async def test_create_discount_coupon(self, svc, mock_db):
        mock_db.execute = AsyncMock(return_value=MagicMock())
        result = await svc.create_coupon(
            tenant_id=_TENANT_ID, name="8折券", coupon_type="discount",
            db=mock_db, discount_rate=80, wechat_sync=False,
        )
        assert result["coupon_type"] == "discount"

    async def test_create_exchange_coupon(self, svc, mock_db):
        mock_db.execute = AsyncMock(return_value=MagicMock())
        result = await svc.create_coupon(
            tenant_id=_TENANT_ID, name="兑换券", coupon_type="exchange",
            db=mock_db, wechat_sync=False,
        )
        assert result["coupon_type"] == "exchange"

    async def test_invalid_coupon_type_raises(self, svc, mock_db):
        with pytest.raises(ValueError, match="不支持的商品券类型"):
            await svc.create_coupon(
                tenant_id=_TENANT_ID, name="bad", coupon_type="invalid_type", db=mock_db,
            )

    async def test_wechat_sync_failure_does_not_block(self, svc, mock_db):
        mock_db.execute = AsyncMock(return_value=MagicMock())
        with patch.object(svc, "_sync_to_wechat", side_effect=Exception("wechat down")):
            result = await svc.create_coupon(
                tenant_id=_TENANT_ID, name="同步失败不影响创建",
                coupon_type="cash", db=mock_db, cash_amount_fen=500, wechat_sync=True,
            )
        assert result["name"] == "同步失败不影响创建"
        assert result["wechat_activity_id"] is None


class TestListCoupons:
    async def test_empty_list(self, svc, mock_db):
        mock_db.execute = AsyncMock(return_value=_mock_result(scalar_value=0))
        result = await svc.list_coupons(tenant_id=_TENANT_ID, db=mock_db)
        assert result["total"] == 0
        assert result["items"] == []

    async def test_with_type_filter(self, svc, mock_db):
        mock_db.execute = AsyncMock(return_value=_mock_result(scalar_value=0))
        result = await svc.list_coupons(tenant_id=_TENANT_ID, db=mock_db, coupon_type="cash")
        assert result["total"] == 0

    async def test_custom_pagination(self, svc, mock_db):
        mock_db.execute = AsyncMock(return_value=_mock_result(scalar_value=0))
        result = await svc.list_coupons(tenant_id=_TENANT_ID, db=mock_db, page=2, size=10)
        assert result["page"] == 2
        assert result["size"] == 10

    async def test_list_respects_limit(self, svc, mock_db):
        mock_db.execute = AsyncMock(return_value=_mock_result(scalar_value=0))
        result = await svc.list_coupons(tenant_id=_TENANT_ID, db=mock_db, size=5)
        assert result["size"] == 5


class TestGetCoupon:
    async def test_get_existing(self, svc, mock_db):
        today = date.today()
        mock_row = {
            "id": uuid.UUID(_COUPON_ID),
            "name": "测试券",
            "description": "desc",
            "coupon_type": "cash",
            "cash_amount_fen": 1000,
            "discount_rate": 0,
            "min_order_fen": 0,
            "total_quantity": 100,
            "claimed_count": 0,
            "expiry_days": 30,
            "start_date": today,
            "end_date": today,
            "is_active": True,
        }

        mock_db.execute = AsyncMock(return_value=_mock_result(one_or_none=mock_row))
        result = await svc.get_coupon(coupon_id=_COUPON_ID, tenant_id=_TENANT_ID, db=mock_db)
        assert result is not None
        assert result["name"] == "测试券"
        assert result["coupon_type"] == "cash"

    async def test_get_not_found(self, svc, mock_db):
        mock_db.execute = AsyncMock(return_value=_mock_result())
        result = await svc.get_coupon(coupon_id=_COUPON_ID, tenant_id=_TENANT_ID, db=mock_db)
        assert result is None


class TestToggleActive:
    async def test_toggle_on(self, svc, mock_db):
        mock_db.execute = AsyncMock(return_value=MagicMock(rowcount=1))
        result = await svc.toggle_active(coupon_id=_COUPON_ID, tenant_id=_TENANT_ID, db=mock_db, is_active=False)
        assert result is True

    async def test_toggle_not_found(self, svc, mock_db):
        mock_db.execute = AsyncMock(return_value=MagicMock(rowcount=0))
        result = await svc.toggle_active(coupon_id=_COUPON_ID, tenant_id=_TENANT_ID, db=mock_db, is_active=True)
        assert result is False


class TestSingleton:
    def test_get_product_coupon_service_returns_singleton(self):
        s1 = get_product_coupon_service()
        s2 = get_product_coupon_service()
        assert s1 is s2
