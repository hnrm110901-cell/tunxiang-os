"""积分商城测试 -- 覆盖6个核心功能

1. 商城商品列表
2. 积分兑换(扣积分+记录+库存-1)
3. 兑换历史
4. 上架商品
5. 成就系统
6. 生日月特权
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from datetime import datetime, date, timezone
from unittest.mock import AsyncMock

import pytest

from services.points_mall import (
    ACHIEVEMENT_DEFINITIONS,
    check_birthday_privilege,
    create_mall_item,
    exchange_item,
    get_achievement_list,
    get_exchange_history,
    list_mall_items,
)


TENANT_ID = str(uuid.uuid4())
CUSTOMER_ID = str(uuid.uuid4())
CARD_ID = str(uuid.uuid4())
ITEM_ID = str(uuid.uuid4())


# ── Mock helpers ─────────────────────────────────────────────

class FakeMappingResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class FakeResult:
    def __init__(self, rows=None, scalar_val=None):
        self._rows = rows or []
        self._scalar_val = scalar_val

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


# ── 1. 商城商品列表 ─────────────────────────────────────────

class TestListMallItems:
    @pytest.mark.asyncio
    async def test_list_all(self):
        items = [
            {"id": "i1", "name": "招牌鱼头", "category": "dish",
             "points_cost": 500, "stock": 10, "image_url": "", "description": ""},
        ]
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(scalar_val=1),  # count
            FakeResult(rows=items),  # items
        ])
        result = await list_mall_items(category=None, tenant_id=TENANT_ID, db=db)
        assert result["total"] == 1
        assert result["page"] == 1

    @pytest.mark.asyncio
    async def test_list_by_category(self):
        db = make_db([
            FakeResult(),
            FakeResult(scalar_val=0),
            FakeResult(rows=[]),
        ])
        result = await list_mall_items(category="coupon", tenant_id=TENANT_ID, db=db)
        assert result["total"] == 0
        assert result["items"] == []


# ── 2. 积分兑换 ─────────────────────────────────────────────

class TestExchangeItem:
    @pytest.mark.asyncio
    async def test_exchange_success(self):
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[{"id": ITEM_ID, "name": "鱼头", "points_cost": 500, "stock": 5}]),
            FakeResult(rows=[{"card_id": CARD_ID, "points": 1000}]),
            FakeResult(),  # deduct points
            FakeResult(),  # deduct stock
            FakeResult(),  # insert exchange record
            FakeResult(),  # insert points log
        ])
        result = await exchange_item(
            customer_id=CUSTOMER_ID, item_id=ITEM_ID,
            points_cost=500, tenant_id=TENANT_ID, db=db,
        )
        assert result["points_deducted"] == 500
        assert result["status"] == "confirmed"
        assert result["item_name"] == "鱼头"

    @pytest.mark.asyncio
    async def test_exchange_insufficient_points(self):
        db = make_db([
            FakeResult(),
            FakeResult(rows=[{"id": ITEM_ID, "name": "鱼头", "points_cost": 500, "stock": 5}]),
            FakeResult(rows=[{"card_id": CARD_ID, "points": 100}]),  # only 100 points
        ])
        with pytest.raises(ValueError, match="insufficient_points"):
            await exchange_item(CUSTOMER_ID, ITEM_ID, 500, TENANT_ID, db)

    @pytest.mark.asyncio
    async def test_exchange_out_of_stock(self):
        db = make_db([
            FakeResult(),
            FakeResult(rows=[{"id": ITEM_ID, "name": "鱼头", "points_cost": 500, "stock": 0}]),
        ])
        with pytest.raises(ValueError, match="item_out_of_stock"):
            await exchange_item(CUSTOMER_ID, ITEM_ID, 500, TENANT_ID, db)

    @pytest.mark.asyncio
    async def test_exchange_item_not_found(self):
        db = make_db([
            FakeResult(),
            FakeResult(rows=[]),  # item not found
        ])
        with pytest.raises(ValueError, match="item_not_found"):
            await exchange_item(CUSTOMER_ID, ITEM_ID, 500, TENANT_ID, db)

    @pytest.mark.asyncio
    async def test_exchange_cost_mismatch(self):
        db = make_db([
            FakeResult(),
            FakeResult(rows=[{"id": ITEM_ID, "name": "鱼头", "points_cost": 500, "stock": 5}]),
        ])
        with pytest.raises(ValueError, match="points_cost_mismatch"):
            await exchange_item(CUSTOMER_ID, ITEM_ID, 999, TENANT_ID, db)


# ── 3. 兑换历史 ─────────────────────────────────────────────

class TestExchangeHistory:
    @pytest.mark.asyncio
    async def test_history_empty(self):
        db = make_db([
            FakeResult(),
            FakeResult(scalar_val=0),
            FakeResult(rows=[]),
        ])
        result = await get_exchange_history(CUSTOMER_ID, TENANT_ID, db)
        assert result["total"] == 0
        assert result["items"] == []

    @pytest.mark.asyncio
    async def test_history_with_records(self):
        now = datetime.now(timezone.utc)
        records = [
            {"id": "e1", "item_id": "i1", "item_name": "鱼头",
             "points_cost": 500, "status": "confirmed", "created_at": now},
        ]
        db = make_db([
            FakeResult(),
            FakeResult(scalar_val=1),
            FakeResult(rows=records),
        ])
        result = await get_exchange_history(CUSTOMER_ID, TENANT_ID, db)
        assert result["total"] == 1
        assert result["items"][0]["item_name"] == "鱼头"


# ── 4. 上架商品 ─────────────────────────────────────────────

class TestCreateMallItem:
    @pytest.mark.asyncio
    async def test_create_dish(self):
        db = make_db([FakeResult(), FakeResult()])
        result = await create_mall_item(
            name="鱼头券", category="dish", points_cost=500,
            stock=100, image_url="https://img.test/fish.jpg",
            tenant_id=TENANT_ID, db=db,
        )
        assert result["name"] == "鱼头券"
        assert result["category"] == "dish"
        assert result["points_cost"] == 500
        assert result["stock"] == 100

    @pytest.mark.asyncio
    async def test_create_invalid_category(self):
        db = make_db([FakeResult()])
        with pytest.raises(ValueError, match="invalid_category"):
            await create_mall_item(
                "test", "invalid", 100, 10, "", TENANT_ID, db,
            )

    @pytest.mark.asyncio
    async def test_create_invalid_cost(self):
        db = make_db([FakeResult()])
        with pytest.raises(ValueError, match="points_cost_must_be_positive"):
            await create_mall_item(
                "test", "dish", 0, 10, "", TENANT_ID, db,
            )


# ── 5. 成就系统 ─────────────────────────────────────────────

class TestAchievements:
    def test_definitions_exist(self):
        assert len(ACHIEVEMENT_DEFINITIONS) >= 5

    def test_all_have_required_fields(self):
        for a in ACHIEVEMENT_DEFINITIONS:
            assert "id" in a
            assert "name" in a
            assert "threshold" in a
            assert "metric" in a
            assert "reward_points" in a

    @pytest.mark.asyncio
    async def test_achievement_list(self):
        metrics = {
            "order_count": 15, "total_spent_fen": 50000,
            "share_count": 3, "review_count": 0,
        }
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[metrics]),  # metrics query
            FakeResult(rows=[("first_order",), ("orders_10",)]),  # earned
        ])
        result = await get_achievement_list(CUSTOMER_ID, TENANT_ID, db)
        assert result["total_count"] == len(ACHIEVEMENT_DEFINITIONS)
        assert result["earned_count"] == 2


# ── 6. 生日特权 ─────────────────────────────────────────────

class TestBirthdayPrivilege:
    @pytest.mark.asyncio
    async def test_birthday_not_set(self):
        db = make_db([
            FakeResult(),
            FakeResult(rows=[{"birthday": None}]),
        ])
        result = await check_birthday_privilege(CUSTOMER_ID, TENANT_ID, db)
        assert result["eligible"] is False
        assert result["reason"] == "birthday_not_set"

    @pytest.mark.asyncio
    async def test_customer_not_found(self):
        db = make_db([
            FakeResult(),
            FakeResult(rows=[]),
        ])
        with pytest.raises(ValueError, match="customer_not_found"):
            await check_birthday_privilege(CUSTOMER_ID, TENANT_ID, db)

    @pytest.mark.asyncio
    async def test_birthday_month_match(self):
        current_month = datetime.now(timezone.utc).month
        birthday = date(1990, current_month, 15)
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[{"birthday": birthday}]),  # customer
            FakeResult(scalar_val=None),  # not yet claimed
        ])
        result = await check_birthday_privilege(CUSTOMER_ID, TENANT_ID, db)
        assert result["eligible"] is True
        assert len(result["rewards"]) == 3
        reward_types = [r["type"] for r in result["rewards"]]
        assert "coupon" in reward_types
        assert "points" in reward_types
        assert "gift" in reward_types
