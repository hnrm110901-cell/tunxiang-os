"""
外卖平台适配器测试

覆盖：
  - 基本功能：拉取订单 / 接单 / 拒单 / 出餐标记 / 菜单同步 / 库存更新
  - 字段映射：平台原始字段 → 屯象统一格式的关键字段校验
  - 异常处理：空原因拒单 / 未知平台 / 工厂注册
"""

import time
from datetime import datetime, timedelta

import pytest

from shared.adapters.delivery_factory import (
    get_delivery_adapter,
    register_delivery_platform,
)
from shared.adapters.delivery_platform_base import (
    DeliveryPlatformAdapter,
    DeliveryPlatformError,
)
from shared.adapters.douyin_delivery_adapter import DOUYIN_STATUS_MAP, DouyinDeliveryAdapter
from shared.adapters.eleme_delivery_adapter import ELEME_STATUS_MAP, ElemeDeliveryAdapter
from shared.adapters.meituan_delivery_adapter import (
    MEITUAN_STATUS_MAP,
    MeituanAPIError,
    MeituanAuthError,
    MeituanClient,
    MeituanDeliveryAdapter,
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  工厂测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestDeliveryFactory:
    """适配器工厂测试"""

    def test_get_meituan_adapter(self) -> None:
        adapter = get_delivery_adapter("meituan")
        assert isinstance(adapter, MeituanDeliveryAdapter)
        assert isinstance(adapter, DeliveryPlatformAdapter)

    def test_get_eleme_adapter(self) -> None:
        adapter = get_delivery_adapter("eleme")
        assert isinstance(adapter, ElemeDeliveryAdapter)
        assert isinstance(adapter, DeliveryPlatformAdapter)

    def test_get_douyin_adapter(self) -> None:
        adapter = get_delivery_adapter("douyin")
        assert isinstance(adapter, DouyinDeliveryAdapter)
        assert isinstance(adapter, DeliveryPlatformAdapter)

    def test_unknown_platform_raises(self) -> None:
        with pytest.raises(ValueError, match="未知的外卖平台"):
            get_delivery_adapter("unknown_platform")

    def test_register_custom_platform(self) -> None:
        """测试注册自定义平台适配器"""

        class FakeAdapter(DeliveryPlatformAdapter):
            async def pull_orders(self, store_id, since):
                return []

            async def accept_order(self, order_id):
                return True

            async def reject_order(self, order_id, reason):
                return True

            async def mark_ready(self, order_id):
                return True

            async def sync_menu(self, store_id, dishes):
                return {"synced": 0, "failed": 0, "errors": []}

            async def update_stock(self, store_id, dish_id, available):
                return True

            async def get_order_detail(self, order_id):
                return {}

            async def close(self):
                pass

        register_delivery_platform("fake", FakeAdapter)
        adapter = get_delivery_adapter("fake")
        assert isinstance(adapter, FakeAdapter)

    def test_register_invalid_class_raises(self) -> None:
        with pytest.raises(TypeError, match="必须继承"):
            register_delivery_platform("bad", dict)  # type: ignore[arg-type]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  美团适配器测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestMeituanDeliveryAdapter:
    """美团外卖适配器测试"""

    @pytest.fixture
    def adapter(self) -> MeituanDeliveryAdapter:
        return MeituanDeliveryAdapter(
            app_key="test_key",
            app_secret="test_secret",
            store_map={"store_001": "mt_poi_888"},
        )

    # ── 基本功能 ─────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_pull_orders(self, adapter: MeituanDeliveryAdapter) -> None:
        since = datetime.now() - timedelta(hours=1)
        orders = await adapter.pull_orders("store_001", since)
        assert len(orders) > 0
        order = orders[0]
        assert order["platform"] == "meituan"
        assert "platform_order_id" in order
        assert "items" in order
        assert isinstance(order["items"], list)
        assert len(order["items"]) > 0

    @pytest.mark.asyncio
    async def test_accept_order(self, adapter: MeituanDeliveryAdapter) -> None:
        result = await adapter.accept_order("MT_ORDER_001")
        assert result is True

    @pytest.mark.asyncio
    async def test_reject_order(self, adapter: MeituanDeliveryAdapter) -> None:
        result = await adapter.reject_order("MT_ORDER_001", "食材不足")
        assert result is True

    @pytest.mark.asyncio
    async def test_reject_order_empty_reason(self, adapter: MeituanDeliveryAdapter) -> None:
        with pytest.raises(DeliveryPlatformError, match="拒单原因不能为空"):
            await adapter.reject_order("MT_ORDER_001", "")

    @pytest.mark.asyncio
    async def test_mark_ready(self, adapter: MeituanDeliveryAdapter) -> None:
        result = await adapter.mark_ready("MT_ORDER_001")
        assert result is True

    @pytest.mark.asyncio
    async def test_get_order_detail(self, adapter: MeituanDeliveryAdapter) -> None:
        detail = await adapter.get_order_detail("MT_ORDER_001")
        assert detail["platform"] == "meituan"
        assert detail["platform_order_id"] == "MT_ORDER_001"
        assert "items" in detail

    @pytest.mark.asyncio
    async def test_update_stock(self, adapter: MeituanDeliveryAdapter) -> None:
        result = await adapter.update_stock("store_001", "FOOD_001", False)
        assert result is True
        result = await adapter.update_stock("store_001", "FOOD_001", True)
        assert result is True

    # ── 菜单同步 ─────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_sync_menu(self, adapter: MeituanDeliveryAdapter) -> None:
        dishes = [
            {"id": "D001", "name": "宫保鸡丁", "price": 28.0, "category_name": "热菜", "is_available": True},
            {"id": "D002", "name": "米饭", "price": 3.0, "category_name": "主食", "is_available": True},
        ]
        result = await adapter.sync_menu("store_001", dishes)
        assert result["synced"] == 2
        assert result["failed"] == 0
        assert result["errors"] == []

    # ── 字段映射 ─────────────────────────────────────────

    def test_order_field_mapping(self, adapter: MeituanDeliveryAdapter) -> None:
        """验证美团订单字段正确映射到屯象统一格式"""
        raw = {
            "order_id": "MT12345",
            "day_seq": "088",
            "status": 2,
            "order_total_price": 5600,
            "detail": '[{"food_name":"红烧肉","quantity":2,"price":2800,"app_food_code":"F01","food_property":"加辣"}]',
            "recipient_phone": "13800001111",
            "recipient_address": "长沙市开福区",
            "delivery_time": "1700000000",
            "caution": "不要葱",
        }
        mapped = adapter._map_order(raw)

        assert mapped["platform"] == "meituan"
        assert mapped["platform_order_id"] == "MT12345"
        assert mapped["day_seq"] == "088"
        assert mapped["status"] == "confirmed"
        assert mapped["total_fen"] == 5600
        assert mapped["customer_phone"] == "13800001111"
        assert mapped["delivery_address"] == "长沙市开福区"
        assert mapped["notes"] == "不要葱"

        item = mapped["items"][0]
        assert item["name"] == "红烧肉"
        assert item["quantity"] == 2
        assert item["price_fen"] == 2800
        assert item["sku_id"] == "F01"
        assert item["notes"] == "加辣"

    def test_dish_to_meituan_mapping(self, adapter: MeituanDeliveryAdapter) -> None:
        """验证屯象菜品 → 美团商品格式映射"""
        dish = {
            "id": "D001",
            "name": "水煮鱼",
            "category_name": "热菜",
            "price": 58.0,
            "unit": "份",
            "specification": "中辣",
            "is_available": True,
        }
        mt_food = adapter._map_dish_to_meituan(dish)
        assert mt_food["app_food_code"] == "D001"
        assert mt_food["food_name"] == "水煮鱼"
        assert mt_food["price"] == 5800  # 元 → 分
        assert mt_food["is_sold_out"] == 0

    def test_status_map_completeness(self) -> None:
        """验证美团状态映射覆盖所有已知状态"""
        expected_codes = {1, 2, 3, 4, 5, 6, 8}
        assert set(MEITUAN_STATUS_MAP.keys()) == expected_codes

    # ── 签名算法（CH-02.7a a2 起 SoT 由 MeituanClient.compute_sign 提供）─

    def test_compute_sign_basic(self, adapter: MeituanDeliveryAdapter) -> None:
        """美团 MD5 签名基本格式（详细规范断言见 TestMeituanClient）"""
        url = f"{adapter.base_url}/order/confirm"
        params = {"app_key": "test_key", "timestamp": "1700000000"}
        sign = MeituanClient.compute_sign(url, params, adapter.app_secret)
        assert isinstance(sign, str)
        assert len(sign) == 32  # MD5 hex length

    # ── 上下文管理器 ─────────────────────────────────────

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        async with MeituanDeliveryAdapter(app_key="k", app_secret="s") as adapter:
            assert isinstance(adapter, DeliveryPlatformAdapter)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  饿了么适配器测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestElemeDeliveryAdapter:
    """饿了么外卖适配器测试"""

    @pytest.fixture
    def adapter(self) -> ElemeDeliveryAdapter:
        return ElemeDeliveryAdapter(
            app_key="test_key",
            app_secret="test_secret",
            store_map={"store_001": "eleme_shop_888"},
        )

    # ── 基本功能 ─────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_pull_orders(self, adapter: ElemeDeliveryAdapter) -> None:
        since = datetime.now() - timedelta(hours=1)
        orders = await adapter.pull_orders("store_001", since)
        assert len(orders) > 0
        order = orders[0]
        assert order["platform"] == "eleme"
        assert "platform_order_id" in order
        assert isinstance(order["items"], list)
        assert len(order["items"]) > 0

    @pytest.mark.asyncio
    async def test_accept_order(self, adapter: ElemeDeliveryAdapter) -> None:
        result = await adapter.accept_order("EL_ORDER_001")
        assert result is True

    @pytest.mark.asyncio
    async def test_reject_order(self, adapter: ElemeDeliveryAdapter) -> None:
        result = await adapter.reject_order("EL_ORDER_001", "暂停营业")
        assert result is True

    @pytest.mark.asyncio
    async def test_reject_order_empty_reason(self, adapter: ElemeDeliveryAdapter) -> None:
        with pytest.raises(DeliveryPlatformError, match="拒单原因不能为空"):
            await adapter.reject_order("EL_ORDER_001", "")

    @pytest.mark.asyncio
    async def test_mark_ready(self, adapter: ElemeDeliveryAdapter) -> None:
        result = await adapter.mark_ready("EL_ORDER_001")
        assert result is True

    @pytest.mark.asyncio
    async def test_get_order_detail(self, adapter: ElemeDeliveryAdapter) -> None:
        detail = await adapter.get_order_detail("EL_ORDER_001")
        assert detail["platform"] == "eleme"
        assert detail["platform_order_id"] == "EL_ORDER_001"

    @pytest.mark.asyncio
    async def test_update_stock(self, adapter: ElemeDeliveryAdapter) -> None:
        result = await adapter.update_stock("store_001", "EL_FOOD_001", False)
        assert result is True

    # ── 菜单同步 ─────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_sync_menu(self, adapter: ElemeDeliveryAdapter) -> None:
        dishes = [
            {"id": "D001", "name": "麻辣香锅", "price": 35.0, "category_name": "热菜", "is_available": True},
        ]
        result = await adapter.sync_menu("store_001", dishes)
        assert result["synced"] == 1
        assert result["failed"] == 0

    # ── 字段映射 ─────────────────────────────────────────

    def test_order_field_mapping(self, adapter: ElemeDeliveryAdapter) -> None:
        """验证饿了么订单字段正确映射到屯象统一格式"""
        raw = {
            "order_id": "EL99999",
            "day_seq": "066",
            "status": 4,
            "total_price": 7800,
            "food_list": [
                {"food_name": "剁椒鱼头", "quantity": 1, "price": 6800, "food_id": "EF01", "remark": "多放剁椒"},
                {"food_name": "白米饭", "quantity": 2, "price": 500, "food_id": "EF02", "remark": ""},
            ],
            "consignee_phone": "15900002222",
            "delivery_address": "长沙市雨花区",
            "expected_delivery_time": "1700000000",
            "remark": "放门口",
        }
        mapped = adapter._map_order(raw)

        assert mapped["platform"] == "eleme"
        assert mapped["platform_order_id"] == "EL99999"
        assert mapped["day_seq"] == "066"
        assert mapped["status"] == "delivering"
        assert mapped["total_fen"] == 7800
        assert mapped["customer_phone"] == "15900002222"
        assert mapped["notes"] == "放门口"
        assert len(mapped["items"]) == 2

        item = mapped["items"][0]
        assert item["name"] == "剁椒鱼头"
        assert item["sku_id"] == "EF01"
        assert item["notes"] == "多放剁椒"

    def test_dish_to_eleme_mapping(self, adapter: ElemeDeliveryAdapter) -> None:
        """验证屯象菜品 → 饿了么商品格式映射"""
        dish = {
            "id": "D001",
            "name": "口味虾",
            "category_name": "招牌菜",
            "price": 128.0,
            "unit": "份",
            "is_available": False,
        }
        el_food = adapter._map_dish_to_eleme(dish)
        assert el_food["food_id"] == "D001"
        assert el_food["name"] == "口味虾"
        assert el_food["price"] == 12800
        assert el_food["is_available"] == 0

    def test_status_map_completeness(self) -> None:
        """验证饿了么状态映射覆盖所有已知状态"""
        expected_codes = {0, 1, 2, 3, 4, 5, 6, 9}
        assert set(ELEME_STATUS_MAP.keys()) == expected_codes

    # ── 签名算法 ─────────────────────────────────────────

    def test_generate_sign(self, adapter: ElemeDeliveryAdapter) -> None:
        """验证 HMAC-SHA256 签名算法基本正确性"""
        params = {"app_key": "test_key", "timestamp": "1700000000"}
        sign = adapter._generate_sign(params)
        assert isinstance(sign, str)
        assert len(sign) == 64  # SHA256 hex length
        assert sign == sign.upper()  # 饿了么签名为大写

    # ── OAuth2 Token 管理 ────────────────────────────────

    @pytest.mark.asyncio
    async def test_token_refresh(self, adapter: ElemeDeliveryAdapter) -> None:
        """验证 Mock token 刷新"""
        token = await adapter.get_access_token()
        assert token.startswith("mock_token_")

        # 第二次应该返回缓存的 token
        token2 = await adapter.get_access_token()
        assert token == token2

    # ── Webhook 处理 ─────────────────────────────────────

    def test_webhook_signature_verification(self, adapter: ElemeDeliveryAdapter) -> None:
        """验证 Webhook 签名校验"""
        import hashlib
        import time as _time

        ts = str(int(_time.time()))
        payload = '{"order_id": "123"}'
        sign_str = f"{adapter.app_secret}{payload}{ts}{adapter.app_secret}"
        valid_sig = hashlib.sha256(sign_str.encode("utf-8")).hexdigest().upper()

        assert adapter.verify_webhook_signature(payload, valid_sig, ts) is True
        assert adapter.verify_webhook_signature(payload, "bad_signature", ts) is False

    @pytest.mark.asyncio
    async def test_webhook_handler_dispatch(self, adapter: ElemeDeliveryAdapter) -> None:
        """验证 Webhook 事件分发"""
        received_events: list[dict] = []

        async def on_order_created(data: dict) -> None:
            received_events.append(data)

        adapter.register_webhook_handler("order.created", on_order_created)
        result = await adapter.handle_webhook_event(
            "order.created",
            {"order_id": "EL123"},
        )
        assert result["success"] is True
        assert len(received_events) == 1
        assert received_events[0]["order_id"] == "EL123"

    @pytest.mark.asyncio
    async def test_webhook_no_handler(self, adapter: ElemeDeliveryAdapter) -> None:
        """验证未注册处理器的事件也不报错"""
        result = await adapter.handle_webhook_event("unknown.event", {})
        assert result["success"] is True
        assert "no handler" in result.get("message", "")

    # ── 上下文管理器 ─────────────────────────────────────

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        async with ElemeDeliveryAdapter(app_key="k", app_secret="s") as adapter:
            assert isinstance(adapter, DeliveryPlatformAdapter)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  抖音外卖适配器测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestDouyinDeliveryAdapter:
    """抖音外卖适配器测试"""

    @pytest.fixture
    def adapter(self) -> DouyinDeliveryAdapter:
        return DouyinDeliveryAdapter(
            app_key="test_key",
            app_secret="test_secret",
            store_map={"store_001": "dy_shop_888"},
        )

    # -- 基本功能 ---------------------------------------------------

    @pytest.mark.asyncio
    async def test_pull_orders(self, adapter: DouyinDeliveryAdapter) -> None:
        since = datetime.now() - timedelta(hours=1)
        orders = await adapter.pull_orders("store_001", since)
        assert len(orders) == 3  # 普通 + 达人探店 + 直播间
        order = orders[0]
        assert order["platform"] == "douyin"
        assert "platform_order_id" in order
        assert "items" in order
        assert isinstance(order["items"], list)
        assert len(order["items"]) > 0

    @pytest.mark.asyncio
    async def test_accept_order(self, adapter: DouyinDeliveryAdapter) -> None:
        result = await adapter.accept_order("DY_ORDER_001")
        assert result is True

    @pytest.mark.asyncio
    async def test_reject_order(self, adapter: DouyinDeliveryAdapter) -> None:
        result = await adapter.reject_order("DY_ORDER_001", "食材不足")
        assert result is True

    @pytest.mark.asyncio
    async def test_reject_order_empty_reason(self, adapter: DouyinDeliveryAdapter) -> None:
        with pytest.raises(DeliveryPlatformError, match="拒单原因不能为空"):
            await adapter.reject_order("DY_ORDER_001", "")

    @pytest.mark.asyncio
    async def test_mark_ready(self, adapter: DouyinDeliveryAdapter) -> None:
        result = await adapter.mark_ready("DY_ORDER_001")
        assert result is True

    @pytest.mark.asyncio
    async def test_get_order_detail(self, adapter: DouyinDeliveryAdapter) -> None:
        detail = await adapter.get_order_detail("DY_ORDER_001")
        assert detail["platform"] == "douyin"
        assert detail["platform_order_id"] == "DY_ORDER_001"
        assert "items" in detail

    @pytest.mark.asyncio
    async def test_update_stock(self, adapter: DouyinDeliveryAdapter) -> None:
        result = await adapter.update_stock("store_001", "DY_FOOD_001", False)
        assert result is True
        result = await adapter.update_stock("store_001", "DY_FOOD_001", True)
        assert result is True

    # -- 菜单同步 ---------------------------------------------------

    @pytest.mark.asyncio
    async def test_sync_menu(self, adapter: DouyinDeliveryAdapter) -> None:
        dishes = [
            {"id": "D001", "name": "剁椒鱼头", "price": 35.0, "category_name": "热菜", "is_available": True},
            {"id": "D002", "name": "米饭", "price": 3.0, "category_name": "主食", "is_available": True},
        ]
        result = await adapter.sync_menu("store_001", dishes)
        assert result["synced"] == 2
        assert result["failed"] == 0
        assert result["errors"] == []

    # -- 抖音特有：达人探店/直播间订单识别 ---------------------------

    @pytest.mark.asyncio
    async def test_influencer_order_detection(self, adapter: DouyinDeliveryAdapter) -> None:
        """验证达人探店订单被正确标记"""
        since = datetime.now() - timedelta(hours=1)
        orders = await adapter.pull_orders("store_001", since)

        # 第二个订单是达人探店
        influencer_order = orders[1]
        assert influencer_order["is_influencer_order"] is True
        assert influencer_order["is_livestream_order"] is False
        assert influencer_order["order_source_type"] == "influencer"

    @pytest.mark.asyncio
    async def test_livestream_order_detection(self, adapter: DouyinDeliveryAdapter) -> None:
        """验证直播间订单被正确标记"""
        since = datetime.now() - timedelta(hours=1)
        orders = await adapter.pull_orders("store_001", since)

        # 第三个订单是直播间
        livestream_order = orders[2]
        assert livestream_order["is_livestream_order"] is True
        assert livestream_order["is_influencer_order"] is False
        assert livestream_order["order_source_type"] == "livestream"

    @pytest.mark.asyncio
    async def test_normal_order_no_special_flags(self, adapter: DouyinDeliveryAdapter) -> None:
        """验证普通订单没有达人/直播标记"""
        since = datetime.now() - timedelta(hours=1)
        orders = await adapter.pull_orders("store_001", since)

        normal_order = orders[0]
        assert normal_order["is_influencer_order"] is False
        assert normal_order["is_livestream_order"] is False
        assert normal_order["order_source_type"] == "normal"

    # -- 字段映射 ---------------------------------------------------

    def test_order_field_mapping(self, adapter: DouyinDeliveryAdapter) -> None:
        """验证抖音订单字段正确映射到屯象统一格式"""
        raw = {
            "order_id": "DY12345",
            "day_seq": "088",
            "status": 2,
            "total_price": 5600,
            "order_source": 0,
            "food_list": [
                {"food_name": "红烧肉", "quantity": 2, "price": 2800, "sku_id": "F01", "remark": "加辣"},
            ],
            "customer_phone": "13800001111",
            "delivery_address": "长沙市开福区",
            "expected_delivery_time": "1700000000",
            "remark": "不要葱",
        }
        mapped = adapter._map_order(raw)

        assert mapped["platform"] == "douyin"
        assert mapped["platform_order_id"] == "DY12345"
        assert mapped["day_seq"] == "088"
        assert mapped["status"] == "confirmed"
        assert mapped["total_fen"] == 5600
        assert mapped["customer_phone"] == "13800001111"
        assert mapped["delivery_address"] == "长沙市开福区"
        assert mapped["notes"] == "不要葱"

        item = mapped["items"][0]
        assert item["name"] == "红烧肉"
        assert item["quantity"] == 2
        assert item["price_fen"] == 2800
        assert item["sku_id"] == "F01"
        assert item["notes"] == "加辣"

    def test_dish_to_douyin_mapping(self, adapter: DouyinDeliveryAdapter) -> None:
        """验证屯象菜品 -> 抖音商品格式映射"""
        dish = {
            "id": "D001",
            "name": "水煮鱼",
            "category_name": "热菜",
            "price": 58.0,
            "unit": "份",
            "specification": "中辣",
            "is_available": True,
        }
        dy_food = adapter._map_dish_to_douyin(dish)
        assert dy_food["sku_id"] == "D001"
        assert dy_food["food_name"] == "水煮鱼"
        assert dy_food["price"] == 5800  # 元 -> 分
        assert dy_food["stock_status"] == 1

    def test_dish_sold_out_mapping(self, adapter: DouyinDeliveryAdapter) -> None:
        """验证售罄菜品映射"""
        dish = {"id": "D002", "name": "已售罄菜品", "price": 10.0, "is_available": False}
        dy_food = adapter._map_dish_to_douyin(dish)
        assert dy_food["stock_status"] == 0

    def test_status_map_completeness(self) -> None:
        """验证抖音状态映射覆盖所有已知状态"""
        expected_codes = {1, 2, 3, 4, 5, 6, 9}
        assert set(DOUYIN_STATUS_MAP.keys()) == expected_codes

    # -- 签名算法 ---------------------------------------------------

    def test_generate_sign(self, adapter: DouyinDeliveryAdapter) -> None:
        """验证 HMAC-SHA256 签名算法基本正确性"""
        params = {"app_key": "test_key", "timestamp": "1700000000"}
        sign = adapter._generate_sign(params)
        assert isinstance(sign, str)
        assert len(sign) == 64  # SHA256 hex length

    def test_sign_deterministic(self, adapter: DouyinDeliveryAdapter) -> None:
        """同一参数多次签名结果一致"""
        params = {"app_key": "test_key", "timestamp": "1700000000"}
        sign1 = adapter._generate_sign(params)
        sign2 = adapter._generate_sign(params)
        assert sign1 == sign2

    # -- Webhook 处理 -----------------------------------------------

    def test_webhook_signature_verification(self, adapter: DouyinDeliveryAdapter) -> None:
        """验证 Webhook 签名校验"""
        import hashlib as _hashlib
        import hmac as _hmac
        import time as _time

        ts = str(int(_time.time()))
        payload = '{"order_id": "DY123"}'
        sign_str = f"{payload}{ts}"
        valid_sig = _hmac.new(
            adapter.app_secret.encode("utf-8"),
            sign_str.encode("utf-8"),
            _hashlib.sha256,
        ).hexdigest()

        assert adapter.verify_webhook_signature(payload, valid_sig, ts) is True
        assert adapter.verify_webhook_signature(payload, "bad_signature", ts) is False

    @pytest.mark.asyncio
    async def test_webhook_handler_dispatch(self, adapter: DouyinDeliveryAdapter) -> None:
        """验证 Webhook 事件分发"""
        received_events: list[dict] = []

        async def on_order_created(data: dict) -> None:
            received_events.append(data)

        adapter.register_webhook_handler("order.created", on_order_created)
        result = await adapter.handle_webhook_event(
            "order.created",
            {"order_id": "DY123"},
        )
        assert result["success"] is True
        assert len(received_events) == 1
        assert received_events[0]["order_id"] == "DY123"

    @pytest.mark.asyncio
    async def test_webhook_no_handler(self, adapter: DouyinDeliveryAdapter) -> None:
        """验证未注册处理器的事件也不报错"""
        result = await adapter.handle_webhook_event("unknown.event", {})
        assert result["success"] is True
        assert "no handler" in result.get("message", "")

    # -- 上下文管理器 -----------------------------------------------

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        async with DouyinDeliveryAdapter(app_key="k", app_secret="s") as adapter:
            assert isinstance(adapter, DeliveryPlatformAdapter)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  微信自有外卖适配器测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


from shared.adapters.wechat_delivery_adapter import WeChatDeliveryAdapter


class TestWeChatDeliveryAdapter:
    """微信自有外卖适配器测试"""

    @pytest.fixture
    def adapter(self) -> WeChatDeliveryAdapter:
        return WeChatDeliveryAdapter(
            app_key="test_key",
            app_secret="test_secret",
            store_map={},
            timeout=10,
        )

    # ── 基本属性 ─────────────────────────────────────────

    def test_commission_rate_zero(self, adapter: WeChatDeliveryAdapter) -> None:
        """微信自有外卖 0% 抽成"""
        assert adapter.COMMISSION_RATE == 0.0
        assert adapter.PLATFORM_NAME == "wechat"

    # ── 创建订单（通过 get_order_detail 验证） ───────────

    @pytest.mark.asyncio
    async def test_get_order_detail(self, adapter: WeChatDeliveryAdapter) -> None:
        """获取订单详情应返回 commission_fen=0"""
        detail = await adapter.get_order_detail("WX-test-001")
        assert detail["platform"] == "wechat"
        assert detail["platform_order_id"] == "WX-test-001"
        assert detail["commission_rate"] == 0.0
        assert detail["commission_fen"] == 0

    # ── 接单 / 拒单 / 出餐 ───────────────────────────────

    @pytest.mark.asyncio
    async def test_accept_order(self, adapter: WeChatDeliveryAdapter) -> None:
        """接受订单（自有外卖默认自动接单）"""
        result = await adapter.accept_order("WX-test-001")
        assert result is True

    @pytest.mark.asyncio
    async def test_reject_order(self, adapter: WeChatDeliveryAdapter) -> None:
        """拒绝订单"""
        result = await adapter.reject_order("WX-test-001", "客户取消")
        assert result is True

    @pytest.mark.asyncio
    async def test_mark_ready(self, adapter: WeChatDeliveryAdapter) -> None:
        """标记出餐完成"""
        result = await adapter.mark_ready("WX-test-001")
        assert result is True

    # ── 拉取订单（自有外卖直接走 tx-trade，pull 返空）────

    @pytest.mark.asyncio
    async def test_pull_orders_empty(self, adapter: WeChatDeliveryAdapter) -> None:
        """自有外卖 pull_orders 返回空列表（订单直接进 tx-trade）"""
        orders = await adapter.pull_orders("store_001", datetime.now())
        assert orders == []

    # ── 配送请求 ─────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_request_delivery_dada(self, adapter: WeChatDeliveryAdapter) -> None:
        """请求达达配送"""
        result = await adapter.request_delivery("WX-001", "dada")
        assert result["ok"] is True
        assert result["provider"] == "dada"
        assert result["delivery_type"] == "third_party"
        assert "tracking_id" in result

    @pytest.mark.asyncio
    async def test_request_delivery_self(self, adapter: WeChatDeliveryAdapter) -> None:
        """请求自配送"""
        result = await adapter.request_delivery("WX-001", "self")
        assert result["ok"] is True
        assert result["delivery_type"] == "self_delivery"
        assert result["estimated_minutes"] == 20

    @pytest.mark.asyncio
    async def test_request_delivery_shunfeng(self, adapter: WeChatDeliveryAdapter) -> None:
        """请求顺丰配送"""
        result = await adapter.request_delivery("WX-001", "shunfeng")
        assert result["ok"] is True
        assert result["provider"] == "shunfeng"

    @pytest.mark.asyncio
    async def test_request_unsupported_provider(self, adapter: WeChatDeliveryAdapter) -> None:
        """不支持的配送商应抛出 DeliveryPlatformError"""
        with pytest.raises(DeliveryPlatformError):
            await adapter.request_delivery("WX-001", "unknown_provider")

    # ── 配送回调 ─────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_handle_callback_delivered(self, adapter: WeChatDeliveryAdapter) -> None:
        """配送完成回调"""
        result = await adapter.handle_delivery_callback({"event": "delivered", "order_id": "WX-001"})
        assert result["ok"] is True
        assert result["status"] == "delivered"

    @pytest.mark.asyncio
    async def test_handle_callback_pickup(self, adapter: WeChatDeliveryAdapter) -> None:
        """骑手取餐回调"""
        result = await adapter.handle_delivery_callback({"event": "pickup", "order_id": "WX-001"})
        assert result["ok"] is True
        assert result["status"] == "picked_up"

    @pytest.mark.asyncio
    async def test_handle_callback_exception(self, adapter: WeChatDeliveryAdapter) -> None:
        """配送异常回调"""
        result = await adapter.handle_delivery_callback({"event": "exception", "order_id": "WX-001"})
        assert result["ok"] is True
        assert result["status"] == "delivery_exception"

    # ── 菜单同步 ─────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_menu_sync(self, adapter: WeChatDeliveryAdapter) -> None:
        """菜单同步（自管理模式），synced 应等于菜品数"""
        result = await adapter.sync_menu("store_001", [{"id": "d1"}, {"id": "d2"}])
        assert result["synced"] == 2
        assert result["failed"] == 0
        assert result["platform"] == "wechat"

    # ── 库存更新 ─────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_update_stock(self, adapter: WeChatDeliveryAdapter) -> None:
        """更新菜品上下架状态"""
        result = await adapter.update_stock("store_001", "d1", True)
        assert result is True
        result = await adapter.update_stock("store_001", "d1", False)
        assert result is True

    # ── 佣金汇总 ─────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_commission_summary_zero(self, adapter: WeChatDeliveryAdapter) -> None:
        """佣金汇总为 0"""
        result = await adapter.get_commission_summary("2026-04-01", "2026-04-07")
        assert result["commission_fen"] == 0
        assert result["commission_rate"] == 0.0
        assert result["ok"] is True

    # ── 上下文管理器 / 资源释放 ──────────────────────────

    @pytest.mark.asyncio
    async def test_close(self, adapter: WeChatDeliveryAdapter) -> None:
        """释放资源不应报错"""
        await adapter.close()

    # ── 工厂注册验证 ─────────────────────────────────────

    def test_wechat_adapter_registered(self) -> None:
        """微信自有外卖适配器已注册到工厂"""
        adapter = get_delivery_adapter("wechat", app_key="k", app_secret="s", store_map={})
        assert adapter is not None
        assert isinstance(adapter, WeChatDeliveryAdapter)
        assert isinstance(adapter, DeliveryPlatformAdapter)
        assert adapter.PLATFORM_NAME == "wechat"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MeituanClient — HTTP 客户端 SoT（CH-02.7a a2 真接入路径反测）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class _FakeMeituanResp:
    """模拟 httpx.Response 子集（仅 raise_for_status + json）"""

    def __init__(self, json_data: dict, status: int = 200) -> None:
        self._json = json_data
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx as _httpx

            req = _httpx.Request("POST", "https://x")
            resp = _httpx.Response(self.status_code, request=req)
            raise _httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=req, response=resp
            )

    def json(self) -> dict:
        return self._json


class TestMeituanClient:
    """美团 HTTP 客户端真接入路径反测（不调真实美团 API，httpx 层 fake）"""

    @pytest.fixture
    def client(self) -> MeituanClient:
        return MeituanClient(
            app_id="test_app",
            app_secret="test_secret",
            base_url="https://example.com/api/v2",
        )

    # ── 签名规范（确定值断言）─────────────────────────────────

    def test_compute_sign_meituan_spec(self) -> None:
        """compute_sign 严格符合美团规范：MD5(url + sorted "k=v" 拼接 + secret)"""
        import hashlib as _hashlib

        url = "https://example.com/api/v2/order/confirm"
        params = {"app_id": "test_app", "timestamp": "1700000000", "order_id": "MT_1"}
        secret = "test_secret"
        sign = MeituanClient.compute_sign(url, params, secret)

        # 手算预期：按 key 字典序 → app_id,order_id,timestamp
        sorted_kv = "app_id=test_apporder_id=MT_1timestamp=1700000000"
        expected = _hashlib.md5(f"{url}{sorted_kv}{secret}".encode("utf-8")).hexdigest().lower()
        assert sign == expected

    def test_verify_callback_sign_accept_and_reject(self) -> None:
        """verify_callback_sign：合法签名接受、非法签名拒绝、'sign' 字段不参与计算"""
        import hashlib as _hashlib

        params = {"order_id": "MT123", "status": "1", "sign": "should_be_filtered_out"}
        secret = "secret"
        sorted_kv = "order_id=MT123status=1"
        valid_sig = _hashlib.md5(f"{sorted_kv}{secret}".encode("utf-8")).hexdigest().lower()

        assert MeituanClient.verify_callback_sign(params, valid_sig, secret) is True
        assert MeituanClient.verify_callback_sign(params, "bad_sig", secret) is False

    # ── OAuth2 token ─────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_ensure_token_cache_hit_skips_refresh(self, client: MeituanClient) -> None:
        """token 未过期前不刷新（_refresh_token 不被调用）"""
        client._access_token = "cached_token"
        client._token_expires_at = time.time() + 3600

        refresh_called = []

        async def _spy_refresh() -> str:
            refresh_called.append(True)
            return "new_token"

        client._refresh_token = _spy_refresh  # type: ignore[method-assign]
        token = await client._ensure_token()
        assert token == "cached_token"
        assert refresh_called == []
        await client.close()

    @pytest.mark.asyncio
    async def test_refresh_token_http_failure_raises_auth_error(
        self, client: MeituanClient
    ) -> None:
        """token HTTP 失败 → MeituanAuthError（不漏 httpx.HTTPStatusError）"""

        async def _fail_post(*args, **kwargs) -> _FakeMeituanResp:
            return _FakeMeituanResp({"error": "invalid_grant"}, status=401)

        client._http.post = _fail_post  # type: ignore[method-assign]
        with pytest.raises(MeituanAuthError):
            await client._refresh_token()
        await client.close()

    # ── _request 业务/网络错误 ───────────────────────────────

    @pytest.mark.asyncio
    async def test_request_business_error_raises_api_error(
        self, client: MeituanClient
    ) -> None:
        """API code != 0/ok 时抛 MeituanAPIError（含 code + message）"""
        client._access_token = "tok"
        client._token_expires_at = time.time() + 3600

        async def _post_with_business_error(*args, **kwargs) -> _FakeMeituanResp:
            return _FakeMeituanResp({"code": 1001, "msg": "门店未授权"})

        client._http.post = _post_with_business_error  # type: ignore[method-assign]

        with pytest.raises(MeituanAPIError) as exc_info:
            await client.confirm_order("MT_1")
        assert exc_info.value.code == 1001
        assert "门店未授权" in exc_info.value.message
        await client.close()

    @pytest.mark.asyncio
    async def test_request_network_retry_then_api_error(
        self, client: MeituanClient
    ) -> None:
        """连续 HTTP 5xx 重试耗尽（max_retries=3）后抛 MeituanAPIError"""
        client.max_retries = 3
        client._access_token = "tok"
        client._token_expires_at = time.time() + 3600

        call_count = []

        async def _post_always_500(*args, **kwargs) -> _FakeMeituanResp:
            call_count.append(True)
            return _FakeMeituanResp({}, status=500)

        client._http.post = _post_always_500  # type: ignore[method-assign]

        with pytest.raises(MeituanAPIError) as exc_info:
            await client.confirm_order("MT_1")
        assert exc_info.value.code == -1
        assert "3次重试后" in exc_info.value.message
        assert len(call_count) == 3
        await client.close()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MeituanDeliveryAdapter — USE_REAL_API 切换反测（CH-02.7a a2）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestMeituanDeliveryAdapterRealApi:
    """USE_REAL_API 环境变量切换 mock ↔ 真接入"""

    def test_default_keeps_mock_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """未设 MEITUAN_DELIVERY_USE_REAL_API 时默认 mock"""
        monkeypatch.delenv("MEITUAN_DELIVERY_USE_REAL_API", raising=False)
        adapter = MeituanDeliveryAdapter(app_key="k", app_secret="s")
        assert adapter._use_real_api is False
        assert adapter._client is None

    @pytest.mark.asyncio
    async def test_real_api_true_accept_calls_client_confirm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """USE_REAL_API=true 时 accept_order 走 client.confirm_order，传入 order_id"""
        monkeypatch.setenv("MEITUAN_DELIVERY_USE_REAL_API", "true")
        adapter = MeituanDeliveryAdapter(app_key="k", app_secret="s")
        assert adapter._use_real_api is True

        called: list[str] = []

        async def _fake_confirm(order_id: str) -> dict:
            called.append(order_id)
            return {"ok": True}

        client = await adapter._ensure_client()
        client.confirm_order = _fake_confirm  # type: ignore[method-assign]

        result = await adapter.accept_order("MT_REAL_1")
        assert result is True
        assert called == ["MT_REAL_1"]
        await adapter.close()

    @pytest.mark.asyncio
    async def test_close_releases_lazy_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """close() 必须关掉 lazy-init 的 MeituanClient 连接池（防 httpx 泄漏）"""
        monkeypatch.setenv("MEITUAN_DELIVERY_USE_REAL_API", "true")
        adapter = MeituanDeliveryAdapter(app_key="k", app_secret="s")
        client = await adapter._ensure_client()
        assert adapter._client is client

        closed = []

        async def _spy_close() -> None:
            closed.append(True)

        client.close = _spy_close  # type: ignore[method-assign]

        await adapter.close()
        assert closed == [True]
        assert adapter._client is None
