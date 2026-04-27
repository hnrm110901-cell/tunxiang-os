"""积分商城增强功能测试 (v345)

覆盖:
  1. 分类 CRUD
  2. 成就可配置化 (seed + 从DB读取)
  3. 过期自动清理 (商品 + 订单)
  4. 连锁scope过滤
  5. 实物发货流转 (ship + confirm_delivery)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from services.points_mall_v2 import (
    cleanup_expired_orders,
    cleanup_expired_products,
    confirm_delivery,
    create_category,
    delete_category,
    get_achievement_list,
    list_categories,
    list_products,
    seed_default_achievements,
    ship_order,
    update_category,
)

TENANT_ID = str(uuid.uuid4())
CUSTOMER_ID = str(uuid.uuid4())
CARD_ID = str(uuid.uuid4())
PRODUCT_ID = str(uuid.uuid4())
ORDER_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
CATEGORY_ID = str(uuid.uuid4())


# ── Mock helpers ─────────────────────────────────────────────


class FakeMappingResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class FakeResult:
    def __init__(self, rows=None, scalar_val=None, rowcount=1):
        self._rows = rows or []
        self._scalar_val = scalar_val
        self.rowcount = rowcount

    def mappings(self):
        return FakeMappingResult(self._rows)

    def scalar(self):
        return self._scalar_val

    def fetchall(self):
        return self._rows


def make_db(side_effects=None):
    db = AsyncMock()
    if side_effects:
        db.execute = AsyncMock(side_effect=side_effects)
    return db


# ══════════════════════════════════════════════════════════════
#  1. 分类 CRUD
# ══════════════════════════════════════════════════════════════


class TestCategories:
    @pytest.mark.asyncio
    async def test_list_categories_empty(self):
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[]),  # SELECT
        ])
        result = await list_categories(tenant_id=TENANT_ID, db=db)
        assert result["total"] == 0
        assert result["items"] == []

    @pytest.mark.asyncio
    async def test_list_categories_with_data(self):
        categories = [
            {
                "id": CATEGORY_ID,
                "category_name": "热销爆品",
                "category_code": "hot",
                "icon_url": "https://img.test/hot.png",
                "sort_order": 0,
                "is_active": True,
            },
        ]
        db = make_db([
            FakeResult(),
            FakeResult(rows=categories),
        ])
        result = await list_categories(tenant_id=TENANT_ID, db=db)
        assert result["total"] == 1
        assert result["items"][0]["category_name"] == "热销爆品"
        assert result["items"][0]["category_code"] == "hot"

    @pytest.mark.asyncio
    async def test_create_category_success(self):
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(),  # INSERT
        ])
        result = await create_category(
            category_name="限时特惠",
            category_code="flash_sale",
            tenant_id=TENANT_ID,
            db=db,
            icon_url="https://img.test/flash.png",
            sort_order=10,
        )
        assert result["category_name"] == "限时特惠"
        assert result["category_code"] == "flash_sale"
        assert result["sort_order"] == 10

    @pytest.mark.asyncio
    async def test_create_category_empty_name_fails(self):
        db = make_db([FakeResult()])
        with pytest.raises(ValueError, match="category_name_and_code_required"):
            await create_category(
                category_name="",
                category_code="test",
                tenant_id=TENANT_ID,
                db=db,
            )

    @pytest.mark.asyncio
    async def test_update_category_success(self):
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[{"id": CATEGORY_ID}]),  # check exists
            FakeResult(),  # UPDATE
        ])
        result = await update_category(
            category_id=CATEGORY_ID,
            tenant_id=TENANT_ID,
            db=db,
            category_name="新名字",
            sort_order=5,
        )
        assert result["updated"] is True

    @pytest.mark.asyncio
    async def test_update_category_not_found(self):
        db = make_db([
            FakeResult(),
            FakeResult(rows=[]),  # not found
        ])
        with pytest.raises(ValueError, match="category_not_found"):
            await update_category(
                category_id=CATEGORY_ID,
                tenant_id=TENANT_ID,
                db=db,
                category_name="x",
            )

    @pytest.mark.asyncio
    async def test_delete_category_success(self):
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[{"id": CATEGORY_ID}], rowcount=1),  # UPDATE RETURNING
        ])
        result = await delete_category(
            category_id=CATEGORY_ID,
            tenant_id=TENANT_ID,
            db=db,
        )
        assert result["deleted"] is True

    @pytest.mark.asyncio
    async def test_delete_category_not_found(self):
        db = make_db([
            FakeResult(),
            FakeResult(rows=[], rowcount=0),  # nothing to delete
        ])
        with pytest.raises(ValueError, match="category_not_found"):
            await delete_category(
                category_id=str(uuid.uuid4()),
                tenant_id=TENANT_ID,
                db=db,
            )


# ══════════════════════════════════════════════════════════════
#  2. 成就可配置化
# ══════════════════════════════════════════════════════════════


class TestAchievementConfigurable:
    @pytest.mark.asyncio
    async def test_seed_default_achievements(self):
        # _set_tenant + 6 x INSERT ON CONFLICT
        side_effects = [FakeResult()] + [FakeResult() for _ in range(6)]
        db = make_db(side_effects)
        result = await seed_default_achievements(tenant_id=TENANT_ID, db=db)
        assert result["total_defaults"] == 6
        assert result["seeded_count"] == 6

    @pytest.mark.asyncio
    async def test_get_achievement_list_from_db(self):
        configs = [
            {
                "id": str(uuid.uuid4()),
                "achievement_code": "first_order",
                "achievement_name": "初来乍到",
                "description": "完成首单",
                "trigger_type": "order_count",
                "trigger_threshold": 1,
                "reward_points": 10,
                "badge_icon_url": "badge_first",
                "sort_order": 0,
            },
            {
                "id": str(uuid.uuid4()),
                "achievement_code": "orders_10",
                "achievement_name": "常客",
                "description": "累计下单10次",
                "trigger_type": "order_count",
                "trigger_threshold": 10,
                "reward_points": 50,
                "badge_icon_url": "badge_regular",
                "sort_order": 10,
            },
        ]
        metrics = {
            "order_count": 15,
            "total_spent_fen": 50000,
            "share_count": 3,
            "review_count": 0,
        }
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=configs),  # config query
            FakeResult(rows=[metrics]),  # metrics query
            FakeResult(rows=[("first_order",), ("orders_10",)]),  # earned
        ])
        result = await get_achievement_list(CUSTOMER_ID, TENANT_ID, db)
        assert result["total_count"] == 2
        assert result["earned_count"] == 2
        assert result["achievements"][0]["name"] == "初来乍到"
        assert result["achievements"][0]["earned"] is True
        assert result["achievements"][1]["progress"] == 100.0  # 15/10 capped at 100

    @pytest.mark.asyncio
    async def test_get_achievement_list_empty_configs(self):
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[]),  # no configs
        ])
        result = await get_achievement_list(CUSTOMER_ID, TENANT_ID, db)
        assert result["total_count"] == 0
        assert result["achievements"] == []


# ══════════════════════════════════════════════════════════════
#  3. 过期自动清理
# ══════════════════════════════════════════════════════════════


class TestExpirationCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_expired_products(self):
        expired_product_id = str(uuid.uuid4())
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[(expired_product_id,)]),  # UPDATE RETURNING
        ])
        result = await cleanup_expired_products(tenant_id=TENANT_ID, db=db)
        assert result["deactivated_count"] == 1
        assert expired_product_id in result["deactivated_product_ids"]

    @pytest.mark.asyncio
    async def test_cleanup_expired_products_none(self):
        db = make_db([
            FakeResult(),
            FakeResult(rows=[]),  # nothing expired
        ])
        result = await cleanup_expired_products(tenant_id=TENANT_ID, db=db)
        assert result["deactivated_count"] == 0

    @pytest.mark.asyncio
    async def test_cleanup_expired_orders(self):
        now = datetime.now(timezone.utc)
        expired_order = {
            "id": ORDER_ID,
            "order_no": "PM-20260101-ABC123",
            "customer_id": CUSTOMER_ID,
            "product_id": PRODUCT_ID,
            "points_deducted": 500,
            "quantity": 1,
        }
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[expired_order]),  # SELECT expired orders
            FakeResult(),  # UPDATE order status
            FakeResult(rows=[{"id": CARD_ID}]),  # SELECT member card
            FakeResult(),  # UPDATE member_cards (refund)
            FakeResult(),  # INSERT points_log
            FakeResult(rows=[{"stock": 10}]),  # SELECT product stock
            FakeResult(),  # UPDATE product stock
        ])
        result = await cleanup_expired_orders(
            tenant_id=TENANT_ID,
            db=db,
            expire_after_days=30,
        )
        assert result["expired_count"] == 1
        assert result["total_points_refunded"] == 500

    @pytest.mark.asyncio
    async def test_cleanup_expired_orders_none(self):
        db = make_db([
            FakeResult(),
            FakeResult(rows=[]),  # no expired orders
        ])
        result = await cleanup_expired_orders(tenant_id=TENANT_ID, db=db)
        assert result["expired_count"] == 0
        assert result["total_points_refunded"] == 0


# ══════════════════════════════════════════════════════════════
#  4. 连锁scope过滤
# ══════════════════════════════════════════════════════════════


class TestScopeFilter:
    @pytest.mark.asyncio
    async def test_list_products_with_store_scope(self):
        """传入 store_id 时，查询应包含 scope 过滤条件"""
        now = datetime.now(timezone.utc)
        products = [
            {
                "id": PRODUCT_ID,
                "name": "门店专属礼品",
                "description": "仅限本店",
                "image_url": "",
                "product_type": "physical",
                "points_required": 100,
                "stock": 50,
                "stock_sold": 5,
                "limit_per_customer": 0,
                "limit_per_period": 0,
                "limit_period_days": 30,
                "sort_order": 0,
                "valid_from": None,
                "valid_until": None,
            },
        ]
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(scalar_val=1),  # COUNT
            FakeResult(rows=products),  # SELECT products
        ])
        result = await list_products(
            tenant_id=TENANT_ID,
            db=db,
            store_id=STORE_ID,
        )
        assert result["total"] == 1
        assert result["items"][0]["name"] == "门店专属礼品"

        # 验证 SQL 中包含了 scope 过滤
        call_args = db.execute.call_args_list
        # COUNT 查询 (第2次调用)
        count_sql = str(call_args[1][0][0].text)
        assert "scope_type" in count_sql
        assert "store_id" in count_sql

    @pytest.mark.asyncio
    async def test_list_products_without_store_scope(self):
        """不传 store_id 时，不添加 scope 过滤"""
        db = make_db([
            FakeResult(),
            FakeResult(scalar_val=0),
            FakeResult(rows=[]),
        ])
        result = await list_products(
            tenant_id=TENANT_ID,
            db=db,
        )
        assert result["total"] == 0

        # 验证 SQL 不包含 scope 过滤
        call_args = db.execute.call_args_list
        count_sql = str(call_args[1][0][0].text)
        assert "scope_type" not in count_sql

    @pytest.mark.asyncio
    async def test_list_products_with_category_filter(self):
        """传入 category_id 时，查询应包含 category 过滤"""
        db = make_db([
            FakeResult(),
            FakeResult(scalar_val=0),
            FakeResult(rows=[]),
        ])
        result = await list_products(
            tenant_id=TENANT_ID,
            db=db,
            category_id=CATEGORY_ID,
        )
        assert result["total"] == 0

        call_args = db.execute.call_args_list
        count_sql = str(call_args[1][0][0].text)
        assert "category_id" in count_sql


# ══════════════════════════════════════════════════════════════
#  5. 实物发货流转
# ══════════════════════════════════════════════════════════════


class TestShipmentFlow:
    @pytest.mark.asyncio
    async def test_ship_order_success(self):
        order_data = {
            "id": ORDER_ID,
            "order_no": "PM-20260101-XYZ789",
            "customer_id": CUSTOMER_ID,
            "product_id": PRODUCT_ID,
            "status": "pending",
            "fulfillment_status": "pending",
            "product_type": "physical",
        }
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[order_data]),  # SELECT order FOR UPDATE
            FakeResult(),  # UPDATE shipping
        ])
        result = await ship_order(
            order_id=ORDER_ID,
            carrier="顺丰速运",
            tracking_no="SF1234567890",
            tenant_id=TENANT_ID,
            db=db,
            operator_id="op-001",
        )
        assert result["fulfillment_status"] == "shipped"
        assert result["shipping_info"]["carrier"] == "顺丰速运"
        assert result["shipping_info"]["tracking_no"] == "SF1234567890"

    @pytest.mark.asyncio
    async def test_ship_order_not_physical(self):
        order_data = {
            "id": ORDER_ID,
            "order_no": "PM-20260101-XYZ789",
            "customer_id": CUSTOMER_ID,
            "product_id": PRODUCT_ID,
            "status": "pending",
            "fulfillment_status": "pending",
            "product_type": "coupon",
        }
        db = make_db([
            FakeResult(),
            FakeResult(rows=[order_data]),
        ])
        with pytest.raises(ValueError, match="only_physical_orders_can_ship"):
            await ship_order(
                order_id=ORDER_ID,
                carrier="顺丰",
                tracking_no="SF123",
                tenant_id=TENANT_ID,
                db=db,
            )

    @pytest.mark.asyncio
    async def test_ship_order_already_shipped(self):
        order_data = {
            "id": ORDER_ID,
            "order_no": "PM-20260101-XYZ789",
            "customer_id": CUSTOMER_ID,
            "product_id": PRODUCT_ID,
            "status": "pending",
            "fulfillment_status": "shipped",
            "product_type": "physical",
        }
        db = make_db([
            FakeResult(),
            FakeResult(rows=[order_data]),
        ])
        with pytest.raises(ValueError, match="cannot_ship_status:shipped"):
            await ship_order(
                order_id=ORDER_ID,
                carrier="顺丰",
                tracking_no="SF123",
                tenant_id=TENANT_ID,
                db=db,
            )

    @pytest.mark.asyncio
    async def test_ship_order_not_found(self):
        db = make_db([
            FakeResult(),
            FakeResult(rows=[]),
        ])
        with pytest.raises(ValueError, match="order_not_found"):
            await ship_order(
                order_id=str(uuid.uuid4()),
                carrier="顺丰",
                tracking_no="SF123",
                tenant_id=TENANT_ID,
                db=db,
            )

    @pytest.mark.asyncio
    async def test_ship_order_empty_carrier(self):
        db = make_db([FakeResult()])
        with pytest.raises(ValueError, match="carrier_and_tracking_no_required"):
            await ship_order(
                order_id=ORDER_ID,
                carrier="",
                tracking_no="SF123",
                tenant_id=TENANT_ID,
                db=db,
            )

    @pytest.mark.asyncio
    async def test_confirm_delivery_success(self):
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(
                rows=[{"id": ORDER_ID, "order_no": "PM-20260101-XYZ789", "customer_id": CUSTOMER_ID}],
                rowcount=1,
            ),  # UPDATE RETURNING
        ])
        result = await confirm_delivery(
            order_id=ORDER_ID,
            tenant_id=TENANT_ID,
            db=db,
        )
        assert result["fulfillment_status"] == "delivered"
        assert result["status"] == "fulfilled"
        assert "fulfilled_at" in result

    @pytest.mark.asyncio
    async def test_confirm_delivery_not_shipped(self):
        db = make_db([
            FakeResult(),
            FakeResult(rows=[], rowcount=0),  # nothing matched
        ])
        with pytest.raises(ValueError, match="order_not_found_or_not_shipped"):
            await confirm_delivery(
                order_id=ORDER_ID,
                tenant_id=TENANT_ID,
                db=db,
            )


# ══════════════════════════════════════════════════════════════
#  6. 完整发货流程集成
# ══════════════════════════════════════════════════════════════


class TestShipmentIntegration:
    @pytest.mark.asyncio
    async def test_full_physical_order_lifecycle(self):
        """验证完整流程: 兑换 -> 发货(shipped) -> 收货(delivered/fulfilled)"""
        # Step 1: ship
        order_data = {
            "id": ORDER_ID,
            "order_no": "PM-20260101-LIFE01",
            "customer_id": CUSTOMER_ID,
            "product_id": PRODUCT_ID,
            "status": "pending",
            "fulfillment_status": "pending",
            "product_type": "physical",
        }
        db_ship = make_db([
            FakeResult(),
            FakeResult(rows=[order_data]),
            FakeResult(),
        ])
        ship_result = await ship_order(
            order_id=ORDER_ID,
            carrier="中通快递",
            tracking_no="ZT20260101001",
            tenant_id=TENANT_ID,
            db=db_ship,
        )
        assert ship_result["fulfillment_status"] == "shipped"

        # Step 2: confirm delivery
        db_deliver = make_db([
            FakeResult(),
            FakeResult(
                rows=[{"id": ORDER_ID, "order_no": "PM-20260101-LIFE01", "customer_id": CUSTOMER_ID}],
                rowcount=1,
            ),
        ])
        deliver_result = await confirm_delivery(
            order_id=ORDER_ID,
            tenant_id=TENANT_ID,
            db=db_deliver,
        )
        assert deliver_result["fulfillment_status"] == "delivered"
        assert deliver_result["status"] == "fulfilled"
