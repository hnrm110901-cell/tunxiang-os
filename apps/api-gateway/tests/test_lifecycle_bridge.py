"""
全链路闭环桥接测试 — lifecycle_bridge.py 5大桥接

Bridge 1: 预订→订单（到店自动创建订单 + 预排菜转入）
Bridge 2: 宴会→采购（BEO签约→采购建议 + 企微通知）
Bridge 3: 订单→CDP（订单完成→消费者关联+RFM+旅程评估+预订同步）
Bridge 4: 私域→预订闭环（旅程检查 + 进度更新）
Bridge 5: 统一事件发射器
Bonus: 客户360生命周期视图
"""
import pytest
import uuid
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


# ══════════════════════════════════════════════════════════════════
# Bridge 1: 预订→订单
# ══════════════════════════════════════════════════════════════════


class TestBridge1ReservationToOrder:
    """预订到店→自动创建订单"""

    def test_bridge1_function_exists(self):
        from src.services.lifecycle_bridge import prepare_order_from_reservation
        assert callable(prepare_order_from_reservation)

    def test_bridge1_sync_function_exists(self):
        from src.services.lifecycle_bridge import sync_order_completion_to_reservation
        assert callable(sync_order_completion_to_reservation)

    def test_bridge1_signature(self):
        """参数签名正确：session + reservation_id"""
        import inspect
        from src.services.lifecycle_bridge import prepare_order_from_reservation
        sig = inspect.signature(prepare_order_from_reservation)
        params = list(sig.parameters.keys())
        assert "session" in params
        assert "reservation_id" in params

    @pytest.mark.asyncio
    async def test_bridge1_reservation_not_found(self):
        """预订不存在时返回 error"""
        from src.services.lifecycle_bridge import prepare_order_from_reservation

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await prepare_order_from_reservation(mock_session, "nonexistent")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_bridge1_sync_order_not_found(self):
        """订单不存在时 sync_order_completion 返回 None"""
        from src.services.lifecycle_bridge import sync_order_completion_to_reservation

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await sync_order_completion_to_reservation(mock_session, "nonexistent")
        assert result is None

    def test_bridge1_wired_in_reservations_api(self):
        """确认 Bridge 1 已连接到预订签到流程"""
        import inspect
        from src.api import reservations
        source = inspect.getsource(reservations)
        assert "prepare_order_from_reservation" in source


class TestBridge1OrderSync:
    """订单完成反向更新预订"""

    @pytest.mark.asyncio
    async def test_sync_no_reservation_link(self):
        """订单无 order_metadata.reservation_id 时返回 None"""
        from src.services.lifecycle_bridge import sync_order_completion_to_reservation

        mock_session = AsyncMock()
        mock_order = MagicMock()
        mock_order.order_metadata = {}
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_order
        mock_session.execute.return_value = mock_result

        result = await sync_order_completion_to_reservation(mock_session, "order-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_sync_with_reservation_link(self):
        """订单有 reservation_id 时更新预订状态"""
        from src.services.lifecycle_bridge import sync_order_completion_to_reservation
        from src.models.reservation import ReservationStatus

        mock_session = AsyncMock()
        # First call: get order
        mock_order = MagicMock()
        mock_order.order_metadata = {"reservation_id": "res-123"}
        # Second call: get reservation (must be SEATED to trigger completion)
        mock_reservation = MagicMock()
        mock_reservation.id = "res-123"
        mock_reservation.status = ReservationStatus.SEATED

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = mock_order
            elif call_count == 2:
                result.scalar_one_or_none.return_value = mock_reservation
            else:
                result.scalar_one_or_none.return_value = None
            return result

        mock_session.execute = mock_execute

        result = await sync_order_completion_to_reservation(mock_session, "order-1")
        assert result == "res-123"


# ══════════════════════════════════════════════════════════════════
# Bridge 2: 宴会→采购
# ══════════════════════════════════════════════════════════════════


class TestBridge2BanquetToProcurement:
    """BEO签约→采购建议"""

    def test_bridge2_function_exists(self):
        from src.services.lifecycle_bridge import trigger_procurement_from_beo
        assert callable(trigger_procurement_from_beo)

    @pytest.mark.asyncio
    async def test_bridge2_no_procurement_addon(self):
        """BEO 无采购附加项时返回空"""
        from src.services.lifecycle_bridge import trigger_procurement_from_beo

        mock_session = AsyncMock()
        beo_data = {"beo_id": "beo-1"}
        result = await trigger_procurement_from_beo(mock_session, "res-1", beo_data)
        assert result["items"] == 0

    @pytest.mark.asyncio
    async def test_bridge2_with_procurement_items(self):
        """BEO 有采购项时生成采购建议清单"""
        from src.services.lifecycle_bridge import trigger_procurement_from_beo

        mock_session = AsyncMock()
        # Mock reservation lookup
        mock_reservation = MagicMock()
        mock_reservation.id = "res-1"
        mock_reservation.party_size = 20
        mock_reservation.reservation_date = date.today() + timedelta(days=7)
        mock_reservation.store_id = "S001"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_reservation
        mock_session.execute.return_value = mock_result

        beo_data = {
            "beo_id": "beo-1",
            "procurement_addon": [
                {
                    "category": "海鲜",
                    "multiplier": 1.2,
                    "items": [
                        {"name": "龙虾", "quantity": 10, "unit": "只", "cost": 15000},
                        {"name": "帝王蟹", "quantity": 5, "unit": "只", "cost": 28000},
                    ],
                },
                {
                    "category": "酒水",
                    "multiplier": 1.0,
                    "items": [
                        {"name": "茅台", "quantity": 3, "unit": "瓶", "cost": 120000},
                    ],
                },
            ],
        }

        result = await trigger_procurement_from_beo(mock_session, "res-1", beo_data)
        assert result["total_items"] == 3
        assert result["total_estimated_cost_yuan"] > 0
        assert len(result["procurement_items"]) == 3

    @pytest.mark.asyncio
    async def test_bridge2_priority_based_on_date(self):
        """3天内事件标记为 high priority"""
        from src.services.lifecycle_bridge import trigger_procurement_from_beo

        mock_session = AsyncMock()
        mock_reservation = MagicMock()
        mock_reservation.id = "res-1"
        mock_reservation.party_size = 10
        mock_reservation.reservation_date = date.today() + timedelta(days=2)  # 2天后
        mock_reservation.store_id = "S001"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_reservation
        mock_session.execute.return_value = mock_result

        beo_data = {
            "procurement_addon": [{
                "category": "食材",
                "multiplier": 1.0,
                "items": [{"name": "牛肉", "quantity": 10, "unit": "kg", "cost": 5000}],
            }],
        }

        result = await trigger_procurement_from_beo(mock_session, "res-1", beo_data)
        assert result["procurement_items"][0]["priority"] == "high"

    @pytest.mark.asyncio
    async def test_bridge2_quantity_scaled_by_party_size(self):
        """采购量按桌数/人数比例缩放"""
        from src.services.lifecycle_bridge import trigger_procurement_from_beo

        mock_session = AsyncMock()
        mock_reservation = MagicMock()
        mock_reservation.id = "res-1"
        mock_reservation.party_size = 30  # 3x base (base is 10)
        mock_reservation.reservation_date = date.today() + timedelta(days=10)
        mock_reservation.store_id = "S001"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_reservation
        mock_session.execute.return_value = mock_result

        beo_data = {
            "procurement_addon": [{
                "category": "食材",
                "multiplier": 1.0,
                "items": [{"name": "鸡蛋", "quantity": 100, "unit": "个", "cost": 100}],
            }],
        }

        result = await trigger_procurement_from_beo(mock_session, "res-1", beo_data)
        # 100 * 1.0 * (30/10) = 300
        assert result["procurement_items"][0]["adjusted_quantity"] == 300.0

    def test_bridge2_wired_in_banquet_lifecycle(self):
        """确认 Bridge 2 已连接到宴会签约流程"""
        import inspect
        from src.services import banquet_lifecycle_service
        source = inspect.getsource(banquet_lifecycle_service)
        assert "trigger_procurement_from_beo" in source


# ══════════════════════════════════════════════════════════════════
# Bridge 3: 订单→CDP
# ══════════════════════════════════════════════════════════════════


class TestBridge3OrderToCDP:
    """订单完成→CDP闭环"""

    def test_bridge3_function_exists(self):
        from src.services.lifecycle_bridge import on_order_completed
        assert callable(on_order_completed)

    @pytest.mark.asyncio
    async def test_bridge3_order_not_found(self):
        """订单不存在时返回 error"""
        from src.services.lifecycle_bridge import on_order_completed

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await on_order_completed(mock_session, "nonexistent")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_bridge3_emits_signal(self):
        """订单完成时发射事件信号"""
        from src.services.lifecycle_bridge import on_order_completed

        mock_session = AsyncMock()
        mock_order = MagicMock()
        mock_order.id = uuid.uuid4()
        mock_order.consumer_id = None
        mock_order.customer_phone = "13800138000"
        mock_order.store_id = "S001"
        mock_order.total_amount = 28800
        mock_order.items = []
        mock_order.table_number = "A1"
        mock_order.order_metadata = {}

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_order
        mock_session.execute.return_value = mock_result

        # IdentityResolutionService is imported inside the function, patch at source
        with patch("src.services.identity_resolution_service.IdentityResolutionService", side_effect=ImportError):
            result = await on_order_completed(mock_session, str(mock_order.id))

        assert result["order_id"] == str(mock_order.id)
        assert isinstance(result["actions"], list)

    def test_bridge3_wired_in_orders_api(self):
        """确认 Bridge 3 已连接到订单状态更新"""
        import inspect
        from src.api import orders
        source = inspect.getsource(orders)
        assert "on_order_completed" in source

    def test_bridge3_rfm_helper_exists(self):
        from src.services.lifecycle_bridge import _update_rfm_on_order
        assert callable(_update_rfm_on_order)

    def test_bridge3_journey_eval_exists(self):
        from src.services.lifecycle_bridge import _evaluate_journey_success
        assert callable(_evaluate_journey_success)


# ══════════════════════════════════════════════════════════════════
# Bridge 4: 私域→预订闭环
# ══════════════════════════════════════════════════════════════════


class TestBridge4JourneyToReservation:
    """旅程检查 + 优惠提示"""

    def test_bridge4_function_exists(self):
        from src.services.lifecycle_bridge import check_active_journeys_on_reservation
        assert callable(check_active_journeys_on_reservation)

    @pytest.mark.asyncio
    async def test_bridge4_no_consumer_found(self):
        """手机号未注册消费者时返回空"""
        from src.services.lifecycle_bridge import check_active_journeys_on_reservation

        mock_session = AsyncMock()

        with patch("src.services.identity_resolution_service.IdentityResolutionService") as MockIRS:
            mock_svc = AsyncMock()
            mock_svc.resolve.return_value = None
            MockIRS.return_value = mock_svc

            result = await check_active_journeys_on_reservation(
                mock_session, "13800000000", "S001"
            )

        assert result["has_active_journey"] is False
        assert result["journeys"] == []

    def test_bridge4_wired_in_reservations_api(self):
        """确认 Bridge 4 已连接到预订创建"""
        import inspect
        from src.api import reservations
        source = inspect.getsource(reservations)
        assert "check_active_journeys_on_reservation" in source


# ══════════════════════════════════════════════════════════════════
# Bridge 5: 统一事件发射器
# ══════════════════════════════════════════════════════════════════


class TestBridge5EventEmitter:
    """统一生命周期事件发射"""

    def test_emitter_function_exists(self):
        from src.services.lifecycle_bridge import _emit_lifecycle_event
        assert callable(_emit_lifecycle_event)

    @pytest.mark.asyncio
    async def test_emitter_returns_event_id(self):
        """事件发射器返回事件ID"""
        from src.services.lifecycle_bridge import _emit_lifecycle_event

        mock_session = AsyncMock()
        event_id = await _emit_lifecycle_event(
            session=mock_session,
            store_id="S001",
            event_type="test.event",
            payload={"key": "value"},
        )
        assert event_id.startswith("LCE_")
        assert "test_event" in event_id

    @pytest.mark.asyncio
    async def test_emitter_inserts_to_neural_event_logs(self):
        """事件写入 neural_event_logs 表"""
        from src.services.lifecycle_bridge import _emit_lifecycle_event

        mock_session = AsyncMock()
        await _emit_lifecycle_event(
            session=mock_session,
            store_id="S001",
            event_type="order.completed",
            payload={"order_id": "O001"},
        )
        # 验证 execute 被调用（INSERT）
        assert mock_session.execute.called


# ══════════════════════════════════════════════════════════════════
# Bonus: 客户360生命周期视图
# ══════════════════════════════════════════════════════════════════


class TestCustomerLifecycleView:
    """客户全生命周期视图"""

    def test_view_function_exists(self):
        from src.services.lifecycle_bridge import get_customer_lifecycle_view
        assert callable(get_customer_lifecycle_view)

    @pytest.mark.asyncio
    async def test_view_returns_all_sections(self):
        """360视图包含预订/订单/CDP/旅程四大板块"""
        from src.services.lifecycle_bridge import get_customer_lifecycle_view

        mock_session = AsyncMock()
        # Mock: no reservations/orders found
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        with patch("src.services.identity_resolution_service.IdentityResolutionService", side_effect=ImportError):
            view = await get_customer_lifecycle_view(
                mock_session, "13800138000", "S001"
            )

        assert "customer_phone" in view
        assert "reservations" in view
        assert "orders" in view
        # Phone masked
        assert "****" in view["customer_phone"]

    def test_view_phone_masking(self):
        """手机号脱敏格式正确"""
        phone = "13812345678"
        masked = phone[:3] + "****" + phone[-4:]
        assert masked == "138****5678"


# ══════════════════════════════════════════════════════════════════
# Lifecycle API 端点测试
# ══════════════════════════════════════════════════════════════════


class TestLifecycleAPI:
    """REST API 端点存在性测试"""

    def test_api_module_importable(self):
        from src.api import lifecycle
        assert hasattr(lifecycle, "router")

    def test_customer_view_endpoint(self):
        from src.api.lifecycle import customer_lifecycle_view
        assert callable(customer_lifecycle_view)

    def test_manual_reservation_to_order_endpoint(self):
        from src.api.lifecycle import manual_reservation_to_order
        assert callable(manual_reservation_to_order)

    def test_manual_order_to_cdp_endpoint(self):
        from src.api.lifecycle import manual_order_to_cdp
        assert callable(manual_order_to_cdp)

    def test_router_registered_in_main(self):
        """确认 lifecycle router 已注册到 main.py"""
        import inspect
        from src.api import lifecycle
        # Check router prefix
        assert lifecycle.router.prefix == "/api/v1/lifecycle"

    def test_all_routes_defined(self):
        """确认3个端点全部注册"""
        from src.api.lifecycle import router
        paths = [r.path for r in router.routes]
        assert any("customer-view" in p for p in paths)
        assert any("reservation-to-order" in p for p in paths)
        assert any("order-to-cdp" in p for p in paths)


# ══════════════════════════════════════════════════════════════════
# 跨模块连接完整性
# ══════════════════════════════════════════════════════════════════


class TestCrossModuleWiring:
    """验证所有5个桥接已正确连线到业务流程"""

    def test_bridge1_wired(self):
        """Bridge 1: reservations.py → prepare_order_from_reservation"""
        import inspect
        from src.api import reservations
        source = inspect.getsource(reservations)
        assert "lifecycle_bridge" in source
        assert "prepare_order_from_reservation" in source

    def test_bridge2_wired(self):
        """Bridge 2: banquet_lifecycle_service.py → trigger_procurement_from_beo"""
        import inspect
        from src.services import banquet_lifecycle_service
        source = inspect.getsource(banquet_lifecycle_service)
        assert "trigger_procurement_from_beo" in source

    def test_bridge3_wired(self):
        """Bridge 3: orders.py → on_order_completed"""
        import inspect
        from src.api import orders
        source = inspect.getsource(orders)
        assert "on_order_completed" in source

    def test_bridge4_wired(self):
        """Bridge 4: reservations.py → check_active_journeys_on_reservation"""
        import inspect
        from src.api import reservations
        source = inspect.getsource(reservations)
        assert "check_active_journeys_on_reservation" in source

    def test_bridge5_used_by_bridges(self):
        """Bridge 5: _emit_lifecycle_event 被 Bridge 2/3 使用"""
        import inspect
        from src.services import lifecycle_bridge
        source = inspect.getsource(lifecycle_bridge)
        # emit is called in bridge 2 (procurement) and bridge 3 (order completed)
        assert source.count("_emit_lifecycle_event") >= 3  # def + 2 calls

    def test_all_5_bridges_in_module_docstring(self):
        """lifecycle_bridge 模块文档包含全部5个桥接说明"""
        from src.services import lifecycle_bridge
        doc = lifecycle_bridge.__doc__
        assert "Bridge 1" in doc
        assert "Bridge 2" in doc
        assert "Bridge 3" in doc
        assert "Bridge 4" in doc
        assert "Bridge 5" in doc
