"""
品智POS适配器（PinzhiPOSAdapter）测试

覆盖：
  - Mock 模式下全部同步接口
  - 订单/菜品/会员/库存同步
  - 订单状态回写
  - 初始化校验
  - 上下文管理器
"""
import pytest
from datetime import datetime, timedelta

from shared.adapters.pinzhi_adapter import (
    PinzhiPOSAdapter,
    PINZHI_ORDER_STATUS_MAP,
    TUNXIANG_TO_PINZHI_STATUS,
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Fixtures
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.fixture
def adapter() -> PinzhiPOSAdapter:
    """Mock 模式品智POS适配器"""
    return PinzhiPOSAdapter(mock_mode=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  初始化测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestPinzhiPOSAdapterInit:
    """初始化校验测试"""

    def test_mock_mode_init_no_credentials_needed(self) -> None:
        """Mock 模式不需要 base_url 和 token"""
        adapter = PinzhiPOSAdapter(mock_mode=True)
        assert adapter.mock_mode is True

    def test_non_mock_missing_base_url_raises(self) -> None:
        """非 Mock 模式缺少 base_url 应抛出 ValueError"""
        with pytest.raises(ValueError, match="PINZHI_BASE_URL 不能为空"):
            PinzhiPOSAdapter(token="some_token", mock_mode=False)

    def test_non_mock_missing_token_raises(self) -> None:
        """非 Mock 模式缺少 token 应抛出 ValueError"""
        with pytest.raises(ValueError, match="PINZHI_TOKEN 不能为空"):
            PinzhiPOSAdapter(base_url="http://example.com", mock_mode=False)

    def test_non_mock_with_credentials_succeeds(self) -> None:
        """非 Mock 模式提供完整凭据应成功初始化"""
        adapter = PinzhiPOSAdapter(
            base_url="http://192.168.1.100:8080/pzcatering-gateway",
            token="test_token",
            mock_mode=False,
        )
        assert adapter.mock_mode is False
        assert adapter._inner is not None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  订单同步测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSyncOrders:
    """订单同步测试"""

    @pytest.mark.asyncio
    async def test_sync_orders_mock(self, adapter: PinzhiPOSAdapter) -> None:
        """Mock 模式返回模拟订单"""
        since = datetime.now() - timedelta(days=1)
        orders = await adapter.sync_orders(since)

        assert isinstance(orders, list)
        assert len(orders) > 0

        order = orders[0]
        assert order["source_system"] == "pinzhi"
        assert order["order_id"] == "PZ_MOCK_001"
        assert order["order_status"] == "completed"
        assert order["order_type"] == "dine_in"
        assert isinstance(order["items"], list)
        assert len(order["items"]) == 2

    @pytest.mark.asyncio
    async def test_sync_orders_items_structure(self, adapter: PinzhiPOSAdapter) -> None:
        """验证订单项结构完整"""
        since = datetime.now() - timedelta(days=1)
        orders = await adapter.sync_orders(since)

        item = orders[0]["items"][0]
        assert "item_id" in item
        assert "dish_id" in item
        assert "dish_name" in item
        assert "quantity" in item
        assert "unit_price_fen" in item
        assert "subtotal_fen" in item

    @pytest.mark.asyncio
    async def test_sync_orders_amounts_in_fen(self, adapter: PinzhiPOSAdapter) -> None:
        """验证金额单位为分"""
        since = datetime.now() - timedelta(days=1)
        orders = await adapter.sync_orders(since)

        order = orders[0]
        assert order["total_fen"] == 9400
        assert order["items"][0]["unit_price_fen"] == 8800
        assert order["items"][0]["subtotal_fen"] == 8800


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  菜品同步测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSyncMenu:
    """菜品同步测试"""

    @pytest.mark.asyncio
    async def test_sync_menu_mock(self, adapter: PinzhiPOSAdapter) -> None:
        """Mock 模式返回模拟菜品"""
        menu = await adapter.sync_menu("OGN001")

        assert isinstance(menu, list)
        assert len(menu) == 2

        dish = menu[0]
        assert dish["source_system"] == "pinzhi"
        assert dish["dish_name"] == "红烧肉"
        assert dish["price_fen"] == 8800
        assert dish["status"] == "active"

    @pytest.mark.asyncio
    async def test_sync_menu_dish_fields(self, adapter: PinzhiPOSAdapter) -> None:
        """验证菜品字段完整"""
        menu = await adapter.sync_menu("OGN001")

        dish = menu[0]
        assert "dish_id" in dish
        assert "dish_name" in dish
        assert "dish_code" in dish
        assert "category_id" in dish
        assert "category_name" in dish
        assert "price_fen" in dish
        assert "cost_fen" in dish
        assert "unit" in dish


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  会员同步测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSyncMembers:
    """会员同步测试"""

    @pytest.mark.asyncio
    async def test_sync_members_mock(self, adapter: PinzhiPOSAdapter) -> None:
        """Mock 模式返回模拟会员"""
        since = datetime.now() - timedelta(days=7)
        members = await adapter.sync_members(since)

        assert isinstance(members, list)
        assert len(members) > 0

        member = members[0]
        assert member["source_system"] == "pinzhi"
        assert member["name"] == "张三"
        assert member["level"] == "gold"

    @pytest.mark.asyncio
    async def test_sync_members_identities(self, adapter: PinzhiPOSAdapter) -> None:
        """验证会员身份标识结构"""
        since = datetime.now() - timedelta(days=7)
        members = await adapter.sync_members(since)

        member = members[0]
        assert isinstance(member["identities"], list)
        assert len(member["identities"]) == 2

        phone_identity = member["identities"][0]
        assert phone_identity["type"] == "phone"
        assert phone_identity["value"] == "13800138001"

        card_identity = member["identities"][1]
        assert card_identity["type"] == "pinzhi_card"
        assert card_identity["value"] == "VIP00001"

    @pytest.mark.asyncio
    async def test_sync_members_golden_id_placeholder(self, adapter: PinzhiPOSAdapter) -> None:
        """验证 golden_id 为 None（由屯象系统分配）"""
        since = datetime.now() - timedelta(days=7)
        members = await adapter.sync_members(since)

        assert members[0]["golden_id"] is None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  库存同步测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSyncInventory:
    """库存同步测试"""

    @pytest.mark.asyncio
    async def test_sync_inventory_mock(self, adapter: PinzhiPOSAdapter) -> None:
        """Mock 模式返回模拟库存"""
        inventory = await adapter.sync_inventory("OGN001")

        assert isinstance(inventory, list)
        assert len(inventory) > 0

        item = inventory[0]
        assert item["source_system"] == "pinzhi"
        assert item["ingredient_name"] == "五花肉"
        assert item["stock_qty"] == 50.0
        assert item["alert_qty"] == 10.0

    @pytest.mark.asyncio
    async def test_sync_inventory_fields(self, adapter: PinzhiPOSAdapter) -> None:
        """验证库存字段完整"""
        inventory = await adapter.sync_inventory("OGN001")

        item = inventory[0]
        assert "ingredient_id" in item
        assert "ingredient_name" in item
        assert "ingredient_code" in item
        assert "unit" in item
        assert "unit_price_fen" in item
        assert "stock_qty" in item
        assert "status" in item


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  订单状态回写测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestPushOrderStatus:
    """订单状态回写测试"""

    @pytest.mark.asyncio
    async def test_push_order_status_mock(self, adapter: PinzhiPOSAdapter) -> None:
        """Mock 模式回写返回成功"""
        result = await adapter.push_order_status("PZ_001", "completed")
        assert result is True

    @pytest.mark.asyncio
    async def test_push_various_statuses(self, adapter: PinzhiPOSAdapter) -> None:
        """测试多种状态回写"""
        for status in ("pending", "confirmed", "preparing", "completed", "cancelled"):
            result = await adapter.push_order_status("PZ_001", status)
            assert result is True

    def test_status_mapping_completeness(self) -> None:
        """验证状态映射覆盖所有品智状态"""
        assert set(PINZHI_ORDER_STATUS_MAP.keys()) == {0, 1, 2}

    def test_tunxiang_to_pinzhi_mapping(self) -> None:
        """验证屯象到品智的状态映射"""
        assert TUNXIANG_TO_PINZHI_STATUS["completed"] == 1
        assert TUNXIANG_TO_PINZHI_STATUS["cancelled"] == 2
        assert TUNXIANG_TO_PINZHI_STATUS["pending"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  上下文管理器测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestContextManager:
    """上下文管理器测试"""

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        """验证 async with 正常工作"""
        async with PinzhiPOSAdapter(mock_mode=True) as adapter:
            assert adapter.mock_mode is True
            orders = await adapter.sync_orders(datetime.now() - timedelta(days=1))
            assert len(orders) > 0

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self) -> None:
        """验证多次 close 不报错"""
        adapter = PinzhiPOSAdapter(mock_mode=True)
        await adapter.close()
        await adapter.close()  # 第二次也不应报错
