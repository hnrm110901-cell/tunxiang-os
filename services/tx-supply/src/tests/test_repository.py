"""InventoryRepository 单元测试 — 使用 mock AsyncSession"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.repository import InventoryRepository


TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())


def _make_ingredient(**overrides):
    i = MagicMock()
    i.id = overrides.get("id", uuid.uuid4())
    i.tenant_id = uuid.UUID(TENANT_ID)
    i.store_id = overrides.get("store_id", uuid.UUID(STORE_ID))
    i.ingredient_name = overrides.get("ingredient_name", "五花肉")
    i.category = overrides.get("category", "meat")
    i.unit = overrides.get("unit", "kg")
    i.current_quantity = overrides.get("current_quantity", 50.0)
    i.min_quantity = overrides.get("min_quantity", 10.0)
    i.max_quantity = overrides.get("max_quantity", 100.0)
    i.unit_price_fen = overrides.get("unit_price_fen", 3500)
    i.status = overrides.get("status", "normal")
    i.supplier_name = overrides.get("supplier_name", "张记肉铺")
    i.created_at = overrides.get("created_at", datetime.now(timezone.utc))
    return i


def _mock_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


# ─── Tests ───


@pytest.mark.asyncio
async def test_list_inventory_paginated():
    """list_inventory 应返回分页格式"""
    session = _mock_session()
    items = [_make_ingredient(ingredient_name="五花肉"), _make_ingredient(ingredient_name="鸡蛋")]

    count_result = MagicMock()
    count_result.scalar.return_value = 2

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = items
    items_result = MagicMock()
    items_result.scalars.return_value = scalars_mock

    session.execute.side_effect = [
        AsyncMock(return_value=None)(),  # set_config
        count_result,
        items_result,
    ]

    repo = InventoryRepository(session, TENANT_ID)
    result = await repo.list_inventory(STORE_ID, page=1, size=20)

    assert result["total"] == 2
    assert result["page"] == 1
    assert len(result["items"]) == 2
    assert result["items"][0]["ingredient_name"] == "五花肉"


@pytest.mark.asyncio
async def test_get_alerts():
    """get_alerts 应返回预警食材列表"""
    session = _mock_session()
    alerts = [
        _make_ingredient(ingredient_name="鲈鱼", status="out_of_stock", current_quantity=0),
        _make_ingredient(ingredient_name="青椒", status="critical", current_quantity=1.0),
        _make_ingredient(ingredient_name="豆腐", status="low", current_quantity=5.0),
    ]

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = alerts
    items_result = MagicMock()
    items_result.scalars.return_value = scalars_mock

    session.execute.side_effect = [
        AsyncMock(return_value=None)(),  # set_config
        items_result,
    ]

    repo = InventoryRepository(session, TENANT_ID)
    result = await repo.get_alerts(STORE_ID)

    assert len(result) == 3
    assert result[0]["ingredient_name"] == "鲈鱼"
    assert result[0]["alert_type"] == "out_of_stock"
    assert result[2]["alert_type"] == "low"


@pytest.mark.asyncio
async def test_adjust_inventory_success():
    """adjust_inventory 正常调整应更新数量并记录流水"""
    session = _mock_session()
    ingredient = _make_ingredient(current_quantity=50.0, min_quantity=10.0, max_quantity=100.0)

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = ingredient

    session.execute.side_effect = [
        AsyncMock(return_value=None)(),  # set_config
        result_mock,
    ]

    repo = InventoryRepository(session, TENANT_ID)
    result = await repo.adjust_inventory(str(ingredient.id), -20.0, "日常消耗")

    assert result["old_quantity"] == 50.0
    assert result["new_quantity"] == 30.0
    assert result["adjustment"] == -20.0
    assert result["status"] == "normal"
    session.add.assert_called_once()  # IngredientTransaction
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_adjust_inventory_insufficient():
    """adjust_inventory 库存不足应抛出 ValueError"""
    session = _mock_session()
    ingredient = _make_ingredient(current_quantity=5.0)

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = ingredient

    session.execute.side_effect = [
        AsyncMock(return_value=None)(),  # set_config
        result_mock,
    ]

    repo = InventoryRepository(session, TENANT_ID)
    with pytest.raises(ValueError, match="Insufficient stock"):
        await repo.adjust_inventory(str(ingredient.id), -10.0, "超出")


@pytest.mark.asyncio
async def test_adjust_inventory_not_found():
    """adjust_inventory 食材不存在应抛出 ValueError"""
    session = _mock_session()

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None

    session.execute.side_effect = [
        AsyncMock(return_value=None)(),  # set_config
        result_mock,
    ]

    repo = InventoryRepository(session, TENANT_ID)
    with pytest.raises(ValueError, match="Ingredient not found"):
        await repo.adjust_inventory(str(uuid.uuid4()), 10.0, "补货")


@pytest.mark.asyncio
async def test_get_waste_top5():
    """get_waste_top5 应返回按金额排序的 Top5"""
    session = _mock_session()

    rows = [
        ("鲈鱼", "seafood", "kg", -5.0, -175000),
        ("牛肉", "meat", "kg", -3.0, -120000),
        ("虾仁", "seafood", "kg", -2.0, -80000),
    ]
    query_result = MagicMock()
    query_result.all.return_value = rows

    session.execute.side_effect = [
        AsyncMock(return_value=None)(),  # set_config
        query_result,
    ]

    repo = InventoryRepository(session, TENANT_ID)
    result = await repo.get_waste_top5(STORE_ID, period="month")

    assert len(result) == 3
    assert result[0]["ingredient_name"] == "鲈鱼"
    assert result[0]["total_waste_fen"] == 175000
    assert result[0]["total_waste_qty"] == 5.0


@pytest.mark.asyncio
async def test_calc_status():
    """_calc_status 应根据库存量返回正确状态"""
    assert InventoryRepository._calc_status(0, 10, 100) == "out_of_stock"
    assert InventoryRepository._calc_status(2, 10, 100) == "critical"
    assert InventoryRepository._calc_status(8, 10, 100) == "low"
    assert InventoryRepository._calc_status(50, 10, 100) == "normal"
