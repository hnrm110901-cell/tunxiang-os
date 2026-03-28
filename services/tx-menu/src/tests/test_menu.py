"""菜单中心完整测试 — dish_service / menu_template / stockout_sync

覆盖: 菜品档案CRUD、按状态/季节筛选、菜单模板、门店发布、
      渠道差异价、季节菜单、包厢菜单、宴席套餐、沽清联动
"""
import sys
import os
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from services.dish_service import (
    create_dish,
    get_dish,
    update_dish,
    delete_dish,
    list_dishes,
    list_dishes_by_status,
    list_dishes_by_season,
    _clear_store,
)
from services.menu_template import (
    create_template,
    get_template,
    list_templates,
    publish_to_store,
    get_store_menu,
    set_channel_price,
    set_seasonal_menu,
    get_seasonal_menu,
    set_room_menu,
    get_room_menu,
    create_banquet_package,
    _clear_all as _clear_templates,
)
from services.stockout_sync import (
    mark_sold_out,
    auto_check_stockout,
    get_sold_out_list,
    restore_dish,
    _clear_all as _clear_stockout,
)

TENANT = str(uuid.uuid4())
STORE = str(uuid.uuid4())


@pytest.fixture(autouse=True)
def _clean():
    """每个测试前清空所有 in-memory 存储"""
    _clear_store()
    _clear_templates()
    _clear_stockout()
    yield
    _clear_store()
    _clear_templates()
    _clear_stockout()


# ═══════════════════════════════════════════
# 1. 菜品档案 CRUD
# ═══════════════════════════════════════════


class TestDishCRUD:
    def test_create_dish_basic(self):
        """创建菜品成功"""
        d = create_dish(
            tenant_id=TENANT,
            dish_name="剁椒鱼头",
            dish_code="DCYT001",
            price_fen=8800,
            cost_fen=3500,
        )
        assert d["dish_name"] == "剁椒鱼头"
        assert d["dish_code"] == "DCYT001"
        assert d["price_fen"] == 8800
        assert d["status"] == "active"
        assert d["is_deleted"] is False

    def test_get_dish(self):
        """获取已创建的菜品"""
        d = create_dish(tenant_id=TENANT, dish_name="小炒肉", dish_code="XCR001", price_fen=4200)
        result = get_dish(d["id"], TENANT)
        assert result is not None
        assert result["dish_name"] == "小炒肉"

    def test_get_dish_not_found(self):
        """获取不存在的菜品返回 None"""
        assert get_dish(str(uuid.uuid4()), TENANT) is None

    def test_update_dish(self):
        """更新菜品字段"""
        d = create_dish(tenant_id=TENANT, dish_name="宫保鸡丁", dish_code="GBJD001", price_fen=3800)
        updated = update_dish(d["id"], TENANT, price_fen=4200, spicy_level=3)
        assert updated["price_fen"] == 4200
        assert updated["spicy_level"] == 3

    def test_delete_dish_soft(self):
        """软删除菜品"""
        d = create_dish(tenant_id=TENANT, dish_name="麻婆豆腐", dish_code="MPDF001", price_fen=2800)
        assert delete_dish(d["id"], TENANT) is True
        assert get_dish(d["id"], TENANT) is None

    def test_delete_nonexistent(self):
        """删除不存在的菜品返回 False"""
        assert delete_dish(str(uuid.uuid4()), TENANT) is False

    def test_duplicate_dish_code_raises(self):
        """重复 dish_code 抛出异常"""
        create_dish(tenant_id=TENANT, dish_name="A", dish_code="DUP001", price_fen=1000)
        with pytest.raises(ValueError, match="dish_code 已存在"):
            create_dish(tenant_id=TENANT, dish_name="B", dish_code="DUP001", price_fen=2000)


# ═══════════════════════════════════════════
# 2. 按状态/季节筛选
# ═══════════════════════════════════════════


class TestDishFilters:
    def test_list_dishes_paginated(self):
        """分页列表"""
        for i in range(5):
            create_dish(tenant_id=TENANT, dish_name=f"菜品{i}", dish_code=f"CP{i:03d}", price_fen=1000 + i * 100)
        result = list_dishes(TENANT, page=1, size=3)
        assert result["total"] == 5
        assert len(result["items"]) == 3
        assert result["page"] == 1

    def test_list_by_status(self):
        """按状态筛选"""
        create_dish(tenant_id=TENANT, dish_name="春卷", dish_code="CJ001", price_fen=1200, is_seasonal=True)
        create_dish(tenant_id=TENANT, dish_name="米饭", dish_code="MF001", price_fen=300)
        seasonal = list_dishes_by_status(TENANT, "seasonal")
        active = list_dishes_by_status(TENANT, "active")
        assert len(seasonal) == 1
        assert seasonal[0]["dish_name"] == "春卷"
        assert len(active) == 1

    def test_list_by_season(self):
        """按季节筛选"""
        create_dish(tenant_id=TENANT, dish_name="冰粉", dish_code="BF001", price_fen=800, season="summer")
        create_dish(tenant_id=TENANT, dish_name="火锅", dish_code="HG001", price_fen=8800, season="winter")
        summer = list_dishes_by_season(TENANT, "summer")
        assert len(summer) == 1
        assert summer[0]["dish_name"] == "冰粉"

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError, match="status"):
            list_dishes_by_status(TENANT, "invalid")


# ═══════════════════════════════════════════
# 3. 菜单模板 + 门店发布
# ═══════════════════════════════════════════


class TestMenuTemplate:
    def test_create_template(self):
        """创建菜单模板"""
        tpl = create_template(
            name="午市标准菜单",
            dishes=[{"dish_id": "d1", "sort_order": 1}, {"dish_id": "d2", "sort_order": 2}],
            tenant_id=TENANT,
        )
        assert tpl["name"] == "午市标准菜单"
        assert len(tpl["dishes"]) == 2
        assert tpl["status"] == "draft"

    def test_publish_to_store(self):
        """发布模板到门店"""
        tpl = create_template(name="全日菜单", dishes=[{"dish_id": "d1"}], tenant_id=TENANT)
        result = publish_to_store(tpl["template_id"], STORE, TENANT)
        assert result["status"] == "success"
        assert result["store_id"] == STORE

        # 验证模板状态更新
        updated = get_template(tpl["template_id"], TENANT)
        assert updated["status"] == "published"
        assert STORE in updated["published_stores"]

    def test_get_store_menu_dine_in(self):
        """获取门店堂食菜单"""
        tpl = create_template(
            name="测试菜单",
            dishes=[{"dish_id": "d1", "price_fen": 3800}],
            tenant_id=TENANT,
        )
        publish_to_store(tpl["template_id"], STORE, TENANT)
        menu = get_store_menu(STORE, "dine_in", TENANT)
        assert menu["dish_count"] == 1
        assert menu["channel"] == "dine_in"

    def test_empty_template_raises(self):
        """空菜品列表模板抛出异常"""
        with pytest.raises(ValueError, match="dishes"):
            create_template(name="空模板", dishes=[], tenant_id=TENANT)


# ═══════════════════════════════════════════
# 4. 渠道差异价
# ═══════════════════════════════════════════


class TestChannelPrice:
    def test_set_and_apply_channel_price(self):
        """设置渠道差异价并在菜单中体现"""
        tpl = create_template(
            name="渠道测试",
            dishes=[{"dish_id": "dish-a", "price_fen": 3800}],
            tenant_id=TENANT,
        )
        publish_to_store(tpl["template_id"], STORE, TENANT)

        # 设置外卖渠道加价
        set_channel_price(dish_id="dish-a", channel="delivery", price_fen=4200, tenant_id=TENANT)

        # 堂食原价
        dine_in_menu = get_store_menu(STORE, "dine_in", TENANT)
        assert dine_in_menu["dishes"][0]["channel_price_fen"] == 3800

        # 外卖差异价
        delivery_menu = get_store_menu(STORE, "delivery", TENANT)
        assert delivery_menu["dishes"][0]["channel_price_fen"] == 4200

    def test_invalid_channel_raises(self):
        with pytest.raises(ValueError, match="channel"):
            set_channel_price(dish_id="d1", channel="invalid", price_fen=1000, tenant_id=TENANT)


# ═══════════════════════════════════════════
# 5. 季节菜单
# ═══════════════════════════════════════════


class TestSeasonalMenu:
    def test_set_and_get_seasonal_menu(self):
        """设置并获取季节菜单"""
        result = set_seasonal_menu(
            store_id=STORE,
            season="summer",
            dishes=[{"dish_id": "d1"}, {"dish_id": "d2"}],
            tenant_id=TENANT,
        )
        assert result["season"] == "summer"
        assert result["dish_count"] == 2

        retrieved = get_seasonal_menu(STORE, "summer", TENANT)
        assert retrieved is not None
        assert len(retrieved["dishes"]) == 2

    def test_invalid_season_raises(self):
        with pytest.raises(ValueError, match="season"):
            set_seasonal_menu(store_id=STORE, season="rainy", dishes=[{"dish_id": "d1"}], tenant_id=TENANT)


# ═══════════════════════════════════════════
# 6. 包厢菜单
# ═══════════════════════════════════════════


class TestRoomMenu:
    def test_set_and_get_room_menu(self):
        """设置并获取 VIP 包厢菜单"""
        result = set_room_menu(
            store_id=STORE,
            room_type="vip",
            dishes=[{"dish_id": "d1"}, {"dish_id": "d2"}, {"dish_id": "d3"}],
            tenant_id=TENANT,
        )
        assert result["room_type"] == "vip"
        assert result["dish_count"] == 3

        retrieved = get_room_menu(STORE, "vip", TENANT)
        assert retrieved is not None

    def test_invalid_room_type_raises(self):
        with pytest.raises(ValueError, match="room_type"):
            set_room_menu(store_id=STORE, room_type="invalid", dishes=[{"dish_id": "d1"}], tenant_id=TENANT)


# ═══════════════════════════════════════════
# 7. 宴席套餐
# ═══════════════════════════════════════════


class TestBanquetPackage:
    def test_create_banquet_package(self):
        """创建宴席套餐"""
        pkg = create_banquet_package(
            name="金秋宴",
            dishes=[{"dish_id": "d1"}, {"dish_id": "d2"}, {"dish_id": "d3"}],
            package_price_fen=88800,
            guest_count=10,
            tenant_id=TENANT,
            description="十人大宴，含酒水",
        )
        assert pkg["name"] == "金秋宴"
        assert pkg["package_price_fen"] == 88800
        assert pkg["guest_count"] == 10
        assert len(pkg["dishes"]) == 3

    def test_zero_guest_raises(self):
        with pytest.raises(ValueError, match="guest_count"):
            create_banquet_package(
                name="X", dishes=[{"dish_id": "d1"}], package_price_fen=1000, guest_count=0, tenant_id=TENANT,
            )


# ═══════════════════════════════════════════
# 8. 沽清联动
# ═══════════════════════════════════════════


class TestStockoutSync:
    def test_mark_sold_out(self):
        """手动标记沽清"""
        record = mark_sold_out(
            dish_id="dish-a",
            store_id=STORE,
            reason="manual",
            tenant_id=TENANT,
            notes="厨师反馈原料用完",
        )
        assert record["status"] == "sold_out"
        assert record["reason"] == "manual"

    def test_get_sold_out_list(self):
        """获取沽清清单"""
        mark_sold_out(dish_id="d1", store_id=STORE, reason="manual", tenant_id=TENANT)
        mark_sold_out(dish_id="d2", store_id=STORE, reason="stock_depleted", tenant_id=TENANT)
        items = get_sold_out_list(STORE, TENANT)
        assert len(items) == 2

    def test_restore_dish(self):
        """恢复沽清菜品"""
        mark_sold_out(dish_id="d1", store_id=STORE, reason="manual", tenant_id=TENANT)
        record = restore_dish("d1", STORE, TENANT)
        assert record["status"] == "restored"
        assert record["restored_at"] is not None

        # 恢复后不再出现在沽清清单
        items = get_sold_out_list(STORE, TENANT)
        assert len(items) == 0

    def test_restore_not_sold_out_raises(self):
        """恢复不在沽清状态的菜品抛出异常"""
        with pytest.raises(ValueError, match="不在沽清状态"):
            restore_dish("nonexistent", STORE, TENANT)

    def test_auto_check_stockout(self):
        """自动检测沽清 — BOM 原料不足"""
        db = {
            "dishes": [
                {
                    "dish_id": "dish-a",
                    "dish_name": "剁椒鱼头",
                    "requires_inventory": True,
                    "ingredients": [
                        {"ingredient_id": "fish-head", "quantity_needed": 1.0},
                        {"ingredient_id": "chili", "quantity_needed": 0.5},
                    ],
                },
                {
                    "dish_id": "dish-b",
                    "dish_name": "小炒肉",
                    "requires_inventory": True,
                    "ingredients": [
                        {"ingredient_id": "pork", "quantity_needed": 0.3},
                    ],
                },
            ],
            "ingredients": {
                "fish-head": {"current_quantity": 0, "min_quantity": 2},  # 耗尽
                "chili": {"current_quantity": 10, "min_quantity": 2},
                "pork": {"current_quantity": 5, "min_quantity": 1},  # 充足
            },
        }

        newly = auto_check_stockout(STORE, TENANT, db)
        assert len(newly) == 1
        assert newly[0]["dish_id"] == "dish-a"
        assert newly[0]["reason"] == "ingredient_short"

    def test_auto_check_no_db(self):
        """无数据源时返回空列表"""
        result = auto_check_stockout(STORE, TENANT)
        assert result == []

    def test_invalid_reason_raises(self):
        """无效沽清原因抛出异常"""
        with pytest.raises(ValueError, match="reason"):
            mark_sold_out(dish_id="d1", store_id=STORE, reason="invalid", tenant_id=TENANT)


# ═══════════════════════════════════════════
# 9. 租户隔离
# ═══════════════════════════════════════════


class TestTenantIsolation:
    def test_cross_tenant_invisible(self):
        """不同租户数据互不可见"""
        other_tenant = str(uuid.uuid4())
        create_dish(tenant_id=TENANT, dish_name="A", dish_code="ISO001", price_fen=1000)
        create_dish(tenant_id=other_tenant, dish_name="B", dish_code="ISO002", price_fen=2000)

        mine = list_dishes(TENANT)
        theirs = list_dishes(other_tenant)
        assert mine["total"] == 1
        assert mine["items"][0]["dish_name"] == "A"
        assert theirs["total"] == 1
        assert theirs["items"][0]["dish_name"] == "B"

    def test_empty_tenant_raises(self):
        """空 tenant_id 抛出异常"""
        with pytest.raises(ValueError, match="tenant_id"):
            create_dish(tenant_id="", dish_name="X", dish_code="X001", price_fen=100)
