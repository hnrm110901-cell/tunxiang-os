"""DishRepository 单元测试 — 使用 mock AsyncSession"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from services.repository import DishRepository

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())


def _make_dish(**overrides):
    """创建 mock Dish 对象"""
    dish = MagicMock()
    dish.id = overrides.get("id", uuid.uuid4())
    dish.tenant_id = uuid.UUID(TENANT_ID)
    dish.dish_name = overrides.get("dish_name", "宫保鸡丁")
    dish.dish_code = overrides.get("dish_code", "GBCJ001")
    dish.category_id = overrides.get("category_id")
    dish.price_fen = overrides.get("price_fen", 3800)
    dish.original_price_fen = overrides.get("original_price_fen")
    dish.cost_fen = overrides.get("cost_fen", 1200)
    dish.profit_margin = overrides.get("profit_margin")
    dish.description = overrides.get("description", "经典川菜")
    dish.image_url = overrides.get("image_url")
    dish.kitchen_station = overrides.get("kitchen_station", "炒锅")
    dish.preparation_time = overrides.get("preparation_time", 15)
    dish.unit = overrides.get("unit", "份")
    dish.spicy_level = overrides.get("spicy_level", 2)
    dish.is_available = overrides.get("is_available", True)
    dish.is_recommended = overrides.get("is_recommended", False)
    dish.sort_order = overrides.get("sort_order", 0)
    dish.total_sales = overrides.get("total_sales", 100)
    dish.total_revenue_fen = overrides.get("total_revenue_fen", 380000)
    dish.rating = overrides.get("rating")
    dish.tags = overrides.get("tags", ["川菜"])
    dish.created_at = overrides.get("created_at", datetime.now(timezone.utc))
    return dish


def _make_category(**overrides):
    cat = MagicMock()
    cat.id = overrides.get("id", uuid.uuid4())
    cat.name = overrides.get("name", "川菜")
    cat.code = overrides.get("code", "CC")
    cat.parent_id = overrides.get("parent_id")
    cat.sort_order = overrides.get("sort_order", 0)
    cat.is_active = overrides.get("is_active", True)
    return cat


def _mock_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


# ─── Tests ───


@pytest.mark.asyncio
async def test_list_dishes_returns_paginated():
    """list_dishes 应返回分页格式"""
    session = _mock_session()
    dishes = [_make_dish(dish_name="菜A"), _make_dish(dish_name="菜B")]

    # mock count query
    count_result = MagicMock()
    count_result.scalar.return_value = 2

    # mock items query
    items_result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = dishes
    items_result.scalars.return_value = scalars_mock

    session.execute.side_effect = [
        AsyncMock(return_value=None)(),  # set_config
        count_result,
        items_result,
    ]

    repo = DishRepository(session, TENANT_ID)
    result = await repo.list_dishes(STORE_ID, page=1, size=20)

    assert result["total"] == 2
    assert result["page"] == 1
    assert result["size"] == 20
    assert len(result["items"]) == 2
    assert result["items"][0]["dish_name"] == "菜A"


@pytest.mark.asyncio
async def test_get_dish_found():
    """get_dish 找到菜品时返回 dict"""
    session = _mock_session()
    dish = _make_dish(dish_name="酸菜鱼")
    dish_id = str(dish.id)

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = dish

    session.execute.side_effect = [
        AsyncMock(return_value=None)(),  # set_config
        result_mock,
    ]

    repo = DishRepository(session, TENANT_ID)
    result = await repo.get_dish(dish_id)

    assert result is not None
    assert result["dish_name"] == "酸菜鱼"
    assert result["id"] == str(dish.id)


@pytest.mark.asyncio
async def test_get_dish_not_found():
    """get_dish 找不到时返回 None"""
    session = _mock_session()

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None

    session.execute.side_effect = [
        AsyncMock(return_value=None)(),  # set_config
        result_mock,
    ]

    repo = DishRepository(session, TENANT_ID)
    result = await repo.get_dish(str(uuid.uuid4()))

    assert result is None


@pytest.mark.asyncio
async def test_create_dish():
    """create_dish 应添加到 session 并返回 dict"""
    session = _mock_session()
    session.execute.return_value = None  # set_config

    repo = DishRepository(session, TENANT_ID)
    data = {
        "dish_name": "麻婆豆腐",
        "dish_code": "MPDF001",
        "price_fen": 2800,
        "category_id": None,
    }
    result = await repo.create_dish(data)

    assert result["dish_name"] == "麻婆豆腐"
    assert result["dish_code"] == "MPDF001"
    assert result["price_fen"] == 2800
    session.add.assert_called_once()
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_dish_success():
    """delete_dish 软删除成功返回 True"""
    session = _mock_session()

    exec_result = MagicMock()
    exec_result.rowcount = 1

    session.execute.side_effect = [
        AsyncMock(return_value=None)(),  # set_config
        exec_result,
    ]

    repo = DishRepository(session, TENANT_ID)
    result = await repo.delete_dish(str(uuid.uuid4()))

    assert result is True


@pytest.mark.asyncio
async def test_list_categories():
    """list_categories 应返回分类列表"""
    session = _mock_session()
    cats = [_make_category(name="川菜"), _make_category(name="粤菜")]

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = cats
    items_result = MagicMock()
    items_result.scalars.return_value = scalars_mock

    session.execute.side_effect = [
        AsyncMock(return_value=None)(),  # set_config
        items_result,
    ]

    repo = DishRepository(session, TENANT_ID)
    result = await repo.list_categories(STORE_ID)

    assert len(result) == 2
    assert result[0]["name"] == "川菜"
    assert result[1]["name"] == "粤菜"
