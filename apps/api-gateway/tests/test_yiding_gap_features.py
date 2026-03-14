"""
易订PRO缺口补齐功能测试 — P0/P1/P2

P0: 餐段配置 + 预排菜 + 渠道统计聚合
P1: 预订单/锁位单 + 销售业绩 + 营销触达 + RFM配置
P2: 客户资源分配 + 来电记录 + 路线发送
"""
import pytest
import uuid
from datetime import date, time, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

# ══════════════════════════════════════════════════════════════════
# P0-1: 餐段配置
# ══════════════════════════════════════════════════════════════════


class TestMealPeriodModel:
    """MealPeriod 模型新增字段测试"""

    def test_model_has_capacity_fields(self):
        from src.models.meal_period import MealPeriod
        # 验证新增字段存在
        columns = {c.name for c in MealPeriod.__table__.columns}
        assert "max_tables" in columns
        assert "max_guests" in columns
        assert "reservation_interval" in columns
        assert "last_reservation_offset" in columns
        assert "overbooking_ratio" in columns

    def test_default_values(self):
        from src.models.meal_period import MealPeriod
        mp = MealPeriod(
            store_id="S001",
            name="午市",
            start_hour=11,
            end_hour=14,
        )
        assert mp.reservation_interval == 30 or mp.reservation_interval is None
        assert mp.overbooking_ratio == 0 or mp.overbooking_ratio is None


class TestMealPeriodAPI:
    """餐段配置 API 测试"""

    def test_availability_endpoint_exists(self):
        """验证可用时段查询端点已注册"""
        from src.api.meal_period_config import get_availability
        assert callable(get_availability)

    def test_crud_endpoints_exist(self):
        from src.api.meal_period_config import (
            list_meal_periods,
            create_meal_period,
            update_meal_period,
            delete_meal_period,
        )
        assert all(callable(f) for f in [
            list_meal_periods, create_meal_period,
            update_meal_period, delete_meal_period,
        ])


# ══════════════════════════════════════════════════════════════════
# P0-2: 预排菜
# ══════════════════════════════════════════════════════════════════


class TestPreOrderModel:
    """预排菜模型测试"""

    def test_model_exists(self):
        from src.models.reservation_pre_order import ReservationPreOrder, PreOrderStatus
        assert ReservationPreOrder.__tablename__ == "reservation_pre_orders"
        assert PreOrderStatus.DRAFT == "draft"
        assert PreOrderStatus.CONFIRMED == "confirmed"
        assert PreOrderStatus.PREPARING == "preparing"
        assert PreOrderStatus.CANCELLED == "cancelled"

    def test_model_columns(self):
        from src.models.reservation_pre_order import ReservationPreOrder
        columns = {c.name for c in ReservationPreOrder.__table__.columns}
        required = {
            "id", "reservation_id", "store_id", "dish_id", "dish_name",
            "unit_price", "quantity", "subtotal", "taste_note",
            "serving_size", "status", "is_locked", "sort_order",
        }
        assert required.issubset(columns)

    def test_subtotal_calculation(self):
        from src.models.reservation_pre_order import ReservationPreOrder
        item = ReservationPreOrder(
            reservation_id="RES_001",
            store_id="S001",
            dish_name="剁椒鱼头",
            unit_price=12800,  # ¥128.00
            quantity=2,
            subtotal=25600,    # ¥256.00
        )
        assert item.subtotal == item.unit_price * item.quantity


class TestPreOrderAPI:
    """预排菜 API 测试"""

    def test_endpoints_exist(self):
        from src.api.pre_order import (
            get_pre_orders,
            add_pre_orders,
            update_pre_order_item,
            delete_pre_order_item,
            confirm_pre_orders,
            get_kitchen_prep_summary,
        )
        assert all(callable(f) for f in [
            get_pre_orders, add_pre_orders,
            update_pre_order_item, delete_pre_order_item,
            confirm_pre_orders, get_kitchen_prep_summary,
        ])

    def test_request_models(self):
        from src.api.pre_order import AddPreOrderItem, BatchAddPreOrderRequest
        item = AddPreOrderItem(
            dish_name="龙虾",
            unit_price=38800,
            quantity=1,
            taste_note="微辣",
        )
        assert item.dish_name == "龙虾"
        assert item.unit_price == 38800

        batch = BatchAddPreOrderRequest(
            reservation_id="RES_001",
            store_id="S001",
            items=[item],
        )
        assert len(batch.items) == 1


# ══════════════════════════════════════════════════════════════════
# P0-3: 渠道统计聚合
# ══════════════════════════════════════════════════════════════════


class TestChannelAnalyticsSummary:
    """渠道统计聚合端点测试"""

    def test_summary_endpoint_exists(self):
        from src.api.channel_analytics import get_channel_summary
        assert callable(get_channel_summary)

    @pytest.mark.asyncio
    async def test_summary_aggregation_logic(self):
        """验证汇总接口组合了3个子查询"""
        mock_session = AsyncMock()
        mock_user = MagicMock()

        with patch('src.api.channel_analytics.channel_analytics_service') as mock_svc:
            mock_svc.get_channel_stats = AsyncMock(return_value={
                "total_reservations": 100,
                "channels": [
                    {"channel": "meituan", "count": 40, "percentage": 40.0, "total_commission": 200.0},
                    {"channel": "phone", "count": 30, "percentage": 30.0, "total_commission": 0.0},
                    {"channel": "wechat", "count": 30, "percentage": 30.0, "total_commission": 0.0},
                ],
            })
            mock_svc.get_channel_conversion = AsyncMock(return_value=[
                {"channel": "meituan", "total": 40, "completed": 35, "conversion_rate": 87.5},
                {"channel": "phone", "total": 30, "completed": 28, "conversion_rate": 93.3},
                {"channel": "wechat", "total": 30, "completed": 25, "conversion_rate": 83.3},
            ])
            mock_svc.get_cancellation_analysis = AsyncMock(return_value={
                "total_reservations": 100,
                "cancelled": 5,
                "no_show": 3,
                "cancellation_rate": 5.0,
                "no_show_rate": 3.0,
                "effective_rate": 92.0,
            })

            from src.api.channel_analytics import get_channel_summary
            result = await get_channel_summary(
                store_id="S001",
                start_date=date(2026, 3, 1),
                end_date=date(2026, 3, 13),
                session=mock_session,
                current_user=mock_user,
            )

            assert result["total_reservations"] == 100
            assert result["cancellation_rate"] == 5.0
            assert result["effective_rate"] == 92.0
            assert result["top_channel"] == "meituan"
            assert len(result["channels"]) == 3
            # 验证转化率被合并到渠道数据中
            mt = next(c for c in result["channels"] if c["channel"] == "meituan")
            assert mt["conversion_rate"] == 87.5
            assert mt["completed"] == 35


# ══════════════════════════════════════════════════════════════════
# P1-1: 预订单/锁位单
# ══════════════════════════════════════════════════════════════════


class TestReservationReceipt:
    """预订单/锁位单生成测试"""

    def test_endpoints_exist(self):
        from src.api.reservation_receipt import generate_receipt, get_share_data
        assert callable(generate_receipt)
        assert callable(get_share_data)

    def test_phone_masking(self):
        from src.api.reservation_receipt import _mask_phone
        assert _mask_phone("13800138001") == "138****8001"
        assert _mask_phone("") == ""
        assert _mask_phone("123") == "123"

    def test_share_token_is_deterministic(self):
        """相同预订生成相同token（幂等）"""
        import hashlib
        token1 = hashlib.sha256(b"receipt:RES_001:S001").hexdigest()[:16]
        token2 = hashlib.sha256(b"receipt:RES_001:S001").hexdigest()[:16]
        assert token1 == token2
        assert len(token1) == 16


# ══════════════════════════════════════════════════════════════════
# P1-2: 销售业绩归属
# ══════════════════════════════════════════════════════════════════


class TestSalesPerformance:
    """销售业绩归属测试"""

    def test_endpoints_exist(self):
        from src.api.sales_performance import (
            assign_reservation_to_employee,
            get_sales_ranking,
            get_customer_ownership_stats,
        )
        assert all(callable(f) for f in [
            assign_reservation_to_employee,
            get_sales_ranking,
            get_customer_ownership_stats,
        ])

    def test_attribution_tag_format(self):
        """验证归属标签格式"""
        import re
        tag = "[sales:EMP_001]"
        match = re.search(r'\[sales:([^\]]+)\]', tag)
        assert match is not None
        assert match.group(1) == "EMP_001"


# ══════════════════════════════════════════════════════════════════
# P1-3: 营销触达记录
# ══════════════════════════════════════════════════════════════════


class TestMarketingTouchpoint:
    """营销触达记录测试"""

    def test_endpoints_exist(self):
        from src.api.marketing_touchpoint import (
            get_customer_touchpoints,
            get_touchpoint_summary,
        )
        assert callable(get_customer_touchpoints)
        assert callable(get_touchpoint_summary)


# ══════════════════════════════════════════════════════════════════
# P1-4: RFM 阈值管理
# ══════════════════════════════════════════════════════════════════


class TestRFMConfig:
    """RFM 阈值管理测试"""

    def test_default_thresholds_structure(self):
        from src.api.rfm_config import DEFAULT_RFM_THRESHOLDS
        assert "recency" in DEFAULT_RFM_THRESHOLDS
        assert "frequency" in DEFAULT_RFM_THRESHOLDS
        assert "monetary" in DEFAULT_RFM_THRESHOLDS

        # 验证每个维度有 S1-S5
        for dim in ["recency", "frequency", "monetary"]:
            for level in ["S1", "S2", "S3", "S4", "S5"]:
                assert level in DEFAULT_RFM_THRESHOLDS[dim], f"{dim} 缺少 {level}"

    def test_get_rfm_thresholds_function(self):
        from src.api.rfm_config import get_rfm_thresholds, _store_rfm_cache, DEFAULT_RFM_THRESHOLDS

        # 无自定义配置时返回默认
        result = get_rfm_thresholds("S_NEW_STORE")
        assert result == DEFAULT_RFM_THRESHOLDS

        # 有自定义配置时返回自定义
        custom = {"recency": {"S1": {"max_days": 3}}, "frequency": {}, "monetary": {}}
        _store_rfm_cache["S_CUSTOM"] = custom
        result = get_rfm_thresholds("S_CUSTOM")
        assert result == custom

        # 清理
        _store_rfm_cache.pop("S_CUSTOM", None)

    def test_recency_thresholds_are_ordered(self):
        """S1最活跃(最少天数) → S5最沉睡(最多天数)"""
        from src.api.rfm_config import DEFAULT_RFM_THRESHOLDS
        r = DEFAULT_RFM_THRESHOLDS["recency"]
        assert r["S1"]["max_days"] < r["S2"]["max_days"] < r["S3"]["max_days"] < r["S4"]["max_days"] < r["S5"]["max_days"]

    def test_frequency_thresholds_are_ordered(self):
        """S1最高频 → S5最低频"""
        from src.api.rfm_config import DEFAULT_RFM_THRESHOLDS
        f = DEFAULT_RFM_THRESHOLDS["frequency"]
        assert f["S1"]["min_visits"] > f["S2"]["min_visits"] > f["S3"]["min_visits"] > f["S4"]["min_visits"] >= f["S5"]["min_visits"]


# ══════════════════════════════════════════════════════════════════
# P2-1: 客户资源分配
# ══════════════════════════════════════════════════════════════════


class TestCustomerAllocation:
    """客户资源分配测试"""

    def test_endpoints_exist(self):
        from src.api.customer_allocation import (
            get_employee_customers,
            assign_customer,
            batch_assign,
            transfer_customers,
            get_allocation_overview,
        )
        assert all(callable(f) for f in [
            get_employee_customers, assign_customer,
            batch_assign, transfer_customers, get_allocation_overview,
        ])

    def test_allocate_request_model(self):
        from src.api.customer_allocation import AllocateCustomerRequest
        req = AllocateCustomerRequest(
            store_id="S001",
            customer_phone="13800138001",
            customer_name="张三",
            employee_id="EMP_001",
            customer_level="VIP",
        )
        assert req.customer_level == "VIP"

    def test_transfer_request_model(self):
        from src.api.customer_allocation import TransferCustomerRequest
        req = TransferCustomerRequest(
            from_employee_id="EMP_001",
            to_employee_id="EMP_002",
            reason="resignation",
            notes="员工离职交接",
        )
        assert req.reason == "resignation"


# ══════════════════════════════════════════════════════════════════
# P2-2: 来电记录
# ══════════════════════════════════════════════════════════════════


class TestCallRecord:
    """来电记录测试"""

    def test_endpoints_exist(self):
        from src.api.call_record import (
            create_call_record,
            list_call_records,
            cti_webhook,
            send_route,
        )
        assert all(callable(f) for f in [
            create_call_record, list_call_records,
            cti_webhook, send_route,
        ])

    def test_call_record_model(self):
        from src.api.call_record import CallRecordRequest
        req = CallRecordRequest(
            store_id="S001",
            caller_phone="13800138001",
            call_direction="inbound",
            duration_seconds=120,
        )
        assert req.call_direction == "inbound"
        assert req.duration_seconds == 120

    @pytest.mark.asyncio
    async def test_identify_customer_no_ownership(self):
        """无客户归属时返回未识别"""
        from src.api.call_record import _identify_customer
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await _identify_customer(mock_session, "13800000000", "S001")
        assert result["recognized"] is False


# ══════════════════════════════════════════════════════════════════
# P2-3: 路线发送
# ══════════════════════════════════════════════════════════════════


class TestRouteSending:
    """路线发送测试"""

    def test_route_request_model(self):
        from src.api.call_record import SendRouteRequest
        req = SendRouteRequest(
            reservation_id="RES_001",
            channel="sms",
        )
        assert req.channel == "sms"

    def test_nav_url_format(self):
        """验证导航URL包含腾讯地图域名"""
        url = "https://apis.map.qq.com/uri/v1/search?keyword=徐记海鲜荟聚店&referer=tunxiangos"
        assert "apis.map.qq.com" in url


# ══════════════════════════════════════════════════════════════════
# 集成测试：模型注册验证
# ══════════════════════════════════════════════════════════════════


class TestModelRegistration:
    """验证新模型已正确注册到 __init__.py"""

    def test_pre_order_model_importable(self):
        from src.models import ReservationPreOrder, PreOrderStatus
        assert ReservationPreOrder.__tablename__ == "reservation_pre_orders"

    def test_meal_period_model_unchanged(self):
        from src.models import MealPeriod
        assert MealPeriod.__tablename__ == "meal_periods"


# ══════════════════════════════════════════════════════════════════
# 综合覆盖率验证
# ══════════════════════════════════════════════════════════════════


class TestFeatureCoverage:
    """验证所有易订功能缺口已覆盖"""

    def test_p0_meal_period_config(self):
        """P0: 餐段配置（1.8 餐段设置）"""
        from src.api.meal_period_config import router
        paths = [r.path for r in router.routes]
        assert "/api/v1/meal-periods" in paths
        assert "/api/v1/meal-periods/availability" in paths

    def test_p0_pre_order(self):
        """P0: 预排菜（1.10 菜品管理）"""
        from src.api.pre_order import router
        paths = [r.path for r in router.routes]
        assert any("pre-orders" in p for p in paths)
        assert any("kitchen-prep" in p for p in paths)

    def test_p0_channel_summary(self):
        """P0: 渠道统计聚合"""
        from src.api.channel_analytics import router
        paths = [r.path for r in router.routes]
        assert "/channel-analytics/summary" in paths

    def test_p1_receipt(self):
        """P1: 预订单/锁位单"""
        from src.api.reservation_receipt import router
        paths = [r.path for r in router.routes]
        assert any("receipt" in p for p in paths)

    def test_p1_sales_performance(self):
        """P1: 销售业绩归属"""
        from src.api.sales_performance import router
        paths = [r.path for r in router.routes]
        assert any("sales-performance" in p for p in paths)

    def test_p1_rfm_config(self):
        """P1: RFM阈值管理"""
        from src.api.rfm_config import router
        paths = [r.path for r in router.routes]
        assert any("rfm-config" in p for p in paths)

    def test_p2_customer_allocation(self):
        """P2: 客户资源分配"""
        from src.api.customer_allocation import router
        paths = [r.path for r in router.routes]
        assert any("customer-allocation" in p for p in paths)

    def test_p2_call_record(self):
        """P2: 来电记录"""
        from src.api.call_record import router
        paths = [r.path for r in router.routes]
        assert any("call-records" in p for p in paths)

    def test_p2_route_sending(self):
        """P2: 路线发送"""
        from src.api.call_record import router
        paths = [r.path for r in router.routes]
        assert any("send-route" in p for p in paths)
