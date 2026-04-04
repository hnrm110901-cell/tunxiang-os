"""
外卖平台适配器测试

覆盖：
  - 基本功能：拉取订单 / 接单 / 拒单 / 出餐标记 / 菜单同步 / 库存更新
  - 字段映射：平台原始字段 → 屯象统一格式的关键字段校验
  - 异常处理：空原因拒单 / 未知平台 / 工厂注册
"""
import pytest
from datetime import datetime, timedelta

from shared.adapters.delivery_platform_base import (
    DeliveryPlatformAdapter,
    DeliveryPlatformError,
)
from shared.adapters.meituan_adapter import MeituanDeliveryAdapter, MEITUAN_STATUS_MAP
from shared.adapters.eleme_adapter import ElemeDeliveryAdapter, ELEME_STATUS_MAP
from shared.adapters.douyin_adapter import DouyinDeliveryAdapter, DOUYIN_STATUS_MAP
from shared.adapters.delivery_factory import (
    get_delivery_adapter,
    register_delivery_platform,
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

    # ── 签名算法 ─────────────────────────────────────────

    def test_generate_sign(self, adapter: MeituanDeliveryAdapter) -> None:
        """验证 MD5 签名算法基本正确性"""
        params = {"app_key": "test_key", "timestamp": "1700000000"}
        sign = adapter._generate_sign(params)
        assert isinstance(sign, str)
        assert len(sign) == 32  # MD5 hex length

    # ── 上下文管理器 ─────────────────────────────────────

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        async with MeituanDeliveryAdapter(
            app_key="k", app_secret="s"
        ) as adapter:
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
        async with ElemeDeliveryAdapter(
            app_key="k", app_secret="s"
        ) as adapter:
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
        async with DouyinDeliveryAdapter(
            app_key="k", app_secret="s"
        ) as adapter:
            assert isinstance(adapter, DeliveryPlatformAdapter)
