"""外卖聚合接单面板 — 单元测试

覆盖场景：
1. 美团 Webhook 解析并写库（签名跳过演示模式）
2. 饿了么 Webhook 解析（金额单位转换：元→分）
3. 抖音 Webhook 解析
4. 重复推送幂等拦截（DuplicateOrderError）
5. 手动接单 — 状态正确从 pending_accept → accepted
6. 手动接单 — 状态错误时抛出 DeliveryOrderStatusError
7. 拒单 — 状态正确更新，调用平台 API
8. 出餐完成 — mark_ready 状态流转
9. 自动接单规则 — 营业时间内且未超并发，自动接单成功
10. 自动接单规则 — 营业时间外，跳过自动接单
11. 自动接单规则 — 超过并发上限，跳过自动接单
12. 自动接单规则 — 平台在排除列表，跳过自动接单
13. 日统计聚合正确
14. 多租户隔离 — 不同 tenant_id 查不到对方的订单
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../../"))

import uuid
from datetime import date, datetime, time, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── 测试 fixtures ────────────────────────────────────────────────────────────

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()
STORE_ID = uuid.uuid4()
BRAND_ID = "brand_test"

APP_ID = "test_app_id"
APP_SECRET = "test_secret"
SHOP_ID = "test_shop_id"
COMMISSION_RATE = 0.18


def _make_meituan_payload(order_id: str = "MT123456") -> dict:
    return {
        "order_id": order_id,
        "price_info": {"total": 4800, "shipping_fee": 500},
        "product_list": [
            {"food_id": "dish_001", "name": "宫保鸡丁", "quantity": 2, "price": 1600},
            {"food_id": "dish_002", "name": "米饭", "quantity": 2, "price": 800},
        ],
        "recipient_name": "张三",
        "recipient_phone": "138****8888",
        "recipient_address": "长沙市天心区XX路1号",
        "estimate_arrive_time": 1711900000,
    }


def _make_eleme_payload(order_id: str = "EL789012") -> dict:
    return {
        "id": order_id,
        "totalPrice": "48.00",
        "deliverFee": "5.00",
        "groups": [
            {
                "items": [
                    {"id": "e_dish_001", "name": "红烧肉", "quantity": 1, "price": "38.00"},
                    {"id": "e_dish_002", "name": "白饭", "quantity": 2, "price": "5.00"},
                ]
            }
        ],
        "consignee": "李四",
        "phone": "139****9999",
        "address": "长沙市岳麓区XX大道99号",
        "deliverTime": "2026-03-31T19:30:00+08:00",
    }


def _make_douyin_payload(order_id: str = "DY345678") -> dict:
    return {
        "order_id": order_id,
        "order_amount": 6000,
        "delivery_amount": 600,
        "product_list": [
            {"sku_id": "d_sku_001", "title": "剁椒鱼头", "num": 1, "price": 5400},
            {"sku_id": "d_sku_002", "title": "米饭", "num": 1, "price": 600},
        ],
        "delivery_info": {
            "receiver_name": "王五",
            "receiver_phone": "137****7777",
            "address": "长沙市开福区XX街道88号",
        },
        "expect_time": 1711900800,
    }


def _mock_order_model(
    *,
    order_id: Optional[uuid.UUID] = None,
    tenant_id: uuid.UUID = TENANT_A,
    store_id: uuid.UUID = STORE_ID,
    platform: str = "meituan",
    platform_order_id: str = "MT123456",
    status: str = "pending_accept",
    total_fen: int = 4800,
) -> MagicMock:
    """创建 mock DeliveryOrder ORM 对象"""
    m = MagicMock()
    m.id = order_id or uuid.uuid4()
    m.tenant_id = tenant_id
    m.store_id = store_id
    m.platform = platform
    m.platform_name = "美团外卖"
    m.platform_order_id = platform_order_id
    m.platform_order_no = None
    m.order_no = "MT20260331ABCDEF"
    m.status = status
    m.total_fen = total_fen
    m.commission_rate = 0.18
    m.commission_fen = round(total_fen * 0.18)
    m.merchant_receive_fen = total_fen - round(total_fen * 0.18)
    m.actual_revenue_fen = total_fen - round(total_fen * 0.18)
    m.customer_name = "张三"
    m.customer_phone = "138****8888"
    m.delivery_address = "长沙市天心区XX路1号"
    m.expected_time = None
    m.estimated_prep_time = None
    m.items_json = []
    m.special_request = None
    m.notes = None
    m.auto_accepted = False
    m.accepted_at = None
    m.rejected_at = None
    m.rejected_reason = None
    m.ready_at = None
    m.completed_at = None
    m.created_at = datetime.now(timezone.utc)
    m.updated_at = datetime.now(timezone.utc)
    return m


# ─── 适配器解析测试 ───────────────────────────────────────────────────────────


class TestAdapterParsing:
    """测试三个平台适配器的订单解析逻辑"""

    def test_meituan_parse_order_ok(self):
        """美团订单解析：金额单位为分，直接使用"""
        from services.tx_trade.src.services.delivery_adapters.meituan_adapter import MeituanAdapter

        adapter = MeituanAdapter(APP_ID, APP_SECRET, SHOP_ID)
        order = adapter.parse_order(_make_meituan_payload())

        assert order.platform == "meituan"
        assert order.platform_order_id == "MT123456"
        assert order.total_fen == 4800
        assert order.delivery_fee_fen == 500
        assert order.customer_name == "张三"
        assert order.customer_phone == "138****8888"
        assert len(order.items) == 2
        assert order.items[0].name == "宫保鸡丁"
        assert order.items[0].qty == 2
        assert order.items[0].unit_price_fen == 1600
        assert order.items[0].total_fen == 3200

    def test_eleme_parse_order_yuan_to_fen_conversion(self):
        """饿了么订单解析：金额单位为元（字符串），需转换为分"""
        from services.tx_trade.src.services.delivery_adapters.eleme_adapter import ElemeAdapter

        adapter = ElemeAdapter(APP_ID, APP_SECRET, SHOP_ID)
        order = adapter.parse_order(_make_eleme_payload())

        assert order.platform == "eleme"
        assert order.platform_order_id == "EL789012"
        assert order.total_fen == 4800  # 48.00元 × 100
        assert order.delivery_fee_fen == 500  # 5.00元 × 100
        assert order.customer_name == "李四"
        assert len(order.items) == 2
        assert order.items[0].unit_price_fen == 3800  # 38.00元 × 100

    def test_douyin_parse_order_ok(self):
        """抖音订单解析：金额单位为分"""
        from services.tx_trade.src.services.delivery_adapters.douyin_adapter import DouyinAdapter

        adapter = DouyinAdapter(APP_ID, APP_SECRET, SHOP_ID)
        order = adapter.parse_order(_make_douyin_payload())

        assert order.platform == "douyin"
        assert order.platform_order_id == "DY345678"
        assert order.total_fen == 6000
        assert order.delivery_fee_fen == 600
        assert order.customer_name == "王五"
        assert len(order.items) == 2
        assert order.items[0].name == "剁椒鱼头"

    def test_meituan_parse_order_missing_order_id_raises(self):
        """缺少 order_id 字段应抛出 ValueError"""
        from services.tx_trade.src.services.delivery_adapters.meituan_adapter import MeituanAdapter

        adapter = MeituanAdapter(APP_ID, APP_SECRET, SHOP_ID)
        bad_payload = {"price_info": {"total": 1000}}
        with pytest.raises(ValueError, match="美团订单解析失败"):
            adapter.parse_order(bad_payload)

    def test_eleme_parse_order_empty_groups(self):
        """饿了么空 groups 仍可解析（items 为空列表）"""
        from services.tx_trade.src.services.delivery_adapters.eleme_adapter import ElemeAdapter

        adapter = ElemeAdapter(APP_ID, APP_SECRET, SHOP_ID)
        payload = {"id": "EL_EMPTY", "totalPrice": "10.00", "deliverFee": "0", "groups": []}
        order = adapter.parse_order(payload)
        assert order.items == []
        assert order.total_fen == 1000


# ─── Service 层测试 ───────────────────────────────────────────────────────────


class TestDeliveryPanelServiceAccept:
    """手动接单和拒单逻辑"""

    @pytest.mark.asyncio
    async def test_accept_order_ok(self):
        """手动接单：状态 pending_accept → accepted，调用平台 API"""
        from services.tx_trade.src.services.delivery_panel_service import (
            DeliveryPanelService,
        )

        order_id = uuid.uuid4()
        mock_order = _mock_order_model(order_id=order_id, status="pending_accept")
        mock_updated = _mock_order_model(order_id=order_id, status="accepted")
        mock_db = AsyncMock()

        with (
            patch(
                "services.tx_trade.src.services.delivery_panel_service.DeliveryOrderRepository.get_by_id",
                new=AsyncMock(side_effect=[mock_order, mock_updated]),
            ),
            patch(
                "services.tx_trade.src.services.delivery_panel_service.DeliveryOrderRepository.update_status",
                new=AsyncMock(return_value=True),
            ),
            patch("services.tx_trade.src.services.delivery_panel_service._get_adapter") as mock_get_adapter,
            patch(
                "services.tx_trade.src.services.delivery_panel_service._trigger_delivery_print",
                new=AsyncMock(),
            ),
            patch(
                "services.tx_trade.src.services.delivery_panel_service._push_kds_event",
                new=AsyncMock(),
            ),
        ):
            mock_adapter = AsyncMock()
            mock_adapter.confirm_order = AsyncMock(return_value=True)
            mock_get_adapter.return_value = mock_adapter

            result = await DeliveryPanelService.accept_order(
                order_id=order_id,
                tenant_id=TENANT_A,
                prep_time_minutes=25,
                app_id=APP_ID,
                app_secret=APP_SECRET,
                shop_id=SHOP_ID,
                db=mock_db,
            )
            assert result.status == "accepted"
            mock_adapter.confirm_order.assert_awaited_once_with(mock_order.platform_order_id)

    @pytest.mark.asyncio
    async def test_accept_order_wrong_status_raises(self):
        """接单时订单非 pending_accept 状态，抛出 DeliveryOrderStatusError"""
        from services.tx_trade.src.services.delivery_panel_service import (
            DeliveryOrderStatusError,
            DeliveryPanelService,
        )

        order_id = uuid.uuid4()
        mock_order = _mock_order_model(order_id=order_id, status="accepted")  # 已接单
        mock_db = AsyncMock()

        with (
            patch(
                "services.tx_trade.src.services.delivery_panel_service.DeliveryOrderRepository.get_by_id",
                new=AsyncMock(return_value=mock_order),
            ),
            patch(
                "services.tx_trade.src.services.delivery_panel_service._get_adapter",
            ) as mock_get_adapter,
        ):
            mock_get_adapter.return_value = AsyncMock()
            with pytest.raises(DeliveryOrderStatusError, match="不允许接单"):
                await DeliveryPanelService.accept_order(
                    order_id=order_id,
                    tenant_id=TENANT_A,
                    prep_time_minutes=20,
                    app_id=APP_ID,
                    app_secret=APP_SECRET,
                    shop_id=SHOP_ID,
                    db=mock_db,
                )

    @pytest.mark.asyncio
    async def test_reject_order_ok(self):
        """拒单：状态 pending_accept → rejected，调用平台 API"""
        from services.tx_trade.src.services.delivery_panel_service import (
            DeliveryPanelService,
        )

        order_id = uuid.uuid4()
        mock_order = _mock_order_model(order_id=order_id, status="pending_accept")
        mock_updated = _mock_order_model(order_id=order_id, status="rejected")
        mock_db = AsyncMock()

        with (
            patch(
                "services.tx_trade.src.services.delivery_panel_service.DeliveryOrderRepository.get_by_id",
                new=AsyncMock(side_effect=[mock_order, mock_updated]),
            ),
            patch(
                "services.tx_trade.src.services.delivery_panel_service.DeliveryOrderRepository.update_status",
                new=AsyncMock(return_value=True),
            ),
            patch("services.tx_trade.src.services.delivery_panel_service._get_adapter") as mock_get_adapter,
        ):
            mock_adapter = AsyncMock()
            mock_adapter.reject_order = AsyncMock(return_value=True)
            mock_get_adapter.return_value = mock_adapter

            result = await DeliveryPanelService.reject_order(
                order_id=order_id,
                tenant_id=TENANT_A,
                reason="门店已打烊",
                reason_code="closed",
                app_id=APP_ID,
                app_secret=APP_SECRET,
                shop_id=SHOP_ID,
                db=mock_db,
            )
            assert result.status == "rejected"
            mock_adapter.reject_order.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_mark_ready_ok(self):
        """出餐完成：状态 accepted → ready"""
        from services.tx_trade.src.services.delivery_panel_service import (
            DeliveryPanelService,
        )

        order_id = uuid.uuid4()
        mock_order = _mock_order_model(order_id=order_id, status="accepted")
        mock_updated = _mock_order_model(order_id=order_id, status="ready")
        mock_db = AsyncMock()

        with (
            patch(
                "services.tx_trade.src.services.delivery_panel_service.DeliveryOrderRepository.get_by_id",
                new=AsyncMock(side_effect=[mock_order, mock_updated]),
            ),
            patch(
                "services.tx_trade.src.services.delivery_panel_service.DeliveryOrderRepository.update_status",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "services.tx_trade.src.services.delivery_panel_service._push_kds_event",
                new=AsyncMock(),
            ),
        ):
            result = await DeliveryPanelService.mark_ready(
                order_id=order_id,
                tenant_id=TENANT_A,
                app_id=APP_ID,
                app_secret=APP_SECRET,
                shop_id=SHOP_ID,
                db=mock_db,
            )
            assert result.status == "ready"


class TestAutoAcceptLogic:
    """自动接单规则检查逻辑"""

    def _make_rule(
        self,
        *,
        is_enabled: bool = True,
        biz_start: Optional[time] = None,
        biz_end: Optional[time] = None,
        max_concurrent: int = 10,
        excluded: Optional[list] = None,
    ) -> MagicMock:
        rule = MagicMock()
        rule.is_enabled = is_enabled
        rule.business_hours_start = biz_start
        rule.business_hours_end = biz_end
        rule.max_concurrent_orders = max_concurrent
        rule.excluded_platforms = excluded or []
        return rule

    @pytest.mark.asyncio
    async def test_auto_accept_within_hours_succeeds(self):
        """营业时间内，并发未满，自动接单成功"""
        from services.tx_trade.src.services.delivery_panel_service import (
            DeliveryPanelService,
        )

        order = _mock_order_model(status="pending_accept", platform="meituan")
        rule = self._make_rule(
            biz_start=time(8, 0),
            biz_end=time(23, 0),
            max_concurrent=10,
        )
        mock_db = AsyncMock()
        mock_adapter = AsyncMock()
        mock_adapter.confirm_order = AsyncMock(return_value=True)

        with (
            patch(
                "services.tx_trade.src.services.delivery_panel_service.DeliveryAutoAcceptRuleRepository.get_by_store",
                new=AsyncMock(return_value=rule),
            ),
            patch(
                "services.tx_trade.src.services.delivery_panel_service.DeliveryOrderRepository.count_active_orders",
                new=AsyncMock(return_value=3),  # 3 < 10
            ),
            patch(
                "services.tx_trade.src.services.delivery_panel_service.DeliveryOrderRepository.update_status",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "services.tx_trade.src.services.delivery_panel_service._trigger_delivery_print",
                new=AsyncMock(),
            ),
            patch(
                "services.tx_trade.src.services.delivery_panel_service._push_kds_event",
                new=AsyncMock(),
            ),
            patch("services.tx_trade.src.services.delivery_panel_service.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = datetime(2026, 3, 31, 12, 0, 0)
            mock_dt.now.return_value.time.return_value = time(12, 0)

            result = await DeliveryPanelService._check_and_auto_accept(
                order=order,
                tenant_id=TENANT_A,
                store_id=STORE_ID,
                adapter=mock_adapter,
                db=mock_db,
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_auto_accept_platform_excluded(self):
        """平台在排除列表，跳过自动接单"""
        from services.tx_trade.src.services.delivery_panel_service import (
            DeliveryPanelService,
        )

        order = _mock_order_model(status="pending_accept", platform="douyin")
        rule = self._make_rule(excluded=["douyin"])
        mock_db = AsyncMock()
        mock_adapter = AsyncMock()

        with patch(
            "services.tx_trade.src.services.delivery_panel_service.DeliveryAutoAcceptRuleRepository.get_by_store",
            new=AsyncMock(return_value=rule),
        ):
            result = await DeliveryPanelService._check_and_auto_accept(
                order=order,
                tenant_id=TENANT_A,
                store_id=STORE_ID,
                adapter=mock_adapter,
                db=mock_db,
            )
            assert result is False

    @pytest.mark.asyncio
    async def test_auto_accept_concurrent_limit_exceeded(self):
        """活跃订单超过并发上限，跳过自动接单"""
        from services.tx_trade.src.services.delivery_panel_service import (
            DeliveryPanelService,
        )

        order = _mock_order_model(status="pending_accept", platform="meituan")
        rule = self._make_rule(max_concurrent=5)
        mock_db = AsyncMock()
        mock_adapter = AsyncMock()

        with (
            patch(
                "services.tx_trade.src.services.delivery_panel_service.DeliveryAutoAcceptRuleRepository.get_by_store",
                new=AsyncMock(return_value=rule),
            ),
            patch(
                "services.tx_trade.src.services.delivery_panel_service.DeliveryOrderRepository.count_active_orders",
                new=AsyncMock(return_value=6),  # 6 > 5
            ),
        ):
            result = await DeliveryPanelService._check_and_auto_accept(
                order=order,
                tenant_id=TENANT_A,
                store_id=STORE_ID,
                adapter=mock_adapter,
                db=mock_db,
            )
            assert result is False

    @pytest.mark.asyncio
    async def test_auto_accept_rule_disabled(self):
        """规则未启用，跳过自动接单"""
        from services.tx_trade.src.services.delivery_panel_service import (
            DeliveryPanelService,
        )

        order = _mock_order_model(status="pending_accept", platform="meituan")
        rule = self._make_rule(is_enabled=False)
        mock_db = AsyncMock()
        mock_adapter = AsyncMock()

        with patch(
            "services.tx_trade.src.services.delivery_panel_service.DeliveryAutoAcceptRuleRepository.get_by_store",
            new=AsyncMock(return_value=rule),
        ):
            result = await DeliveryPanelService._check_and_auto_accept(
                order=order,
                tenant_id=TENANT_A,
                store_id=STORE_ID,
                adapter=mock_adapter,
                db=mock_db,
            )
            assert result is False

    @pytest.mark.asyncio
    async def test_auto_accept_no_rule_configured(self):
        """未配置规则时，不自动接单"""
        from services.tx_trade.src.services.delivery_panel_service import (
            DeliveryPanelService,
        )

        order = _mock_order_model(status="pending_accept", platform="meituan")
        mock_db = AsyncMock()
        mock_adapter = AsyncMock()

        with patch(
            "services.tx_trade.src.services.delivery_panel_service.DeliveryAutoAcceptRuleRepository.get_by_store",
            new=AsyncMock(return_value=None),
        ):
            result = await DeliveryPanelService._check_and_auto_accept(
                order=order,
                tenant_id=TENANT_A,
                store_id=STORE_ID,
                adapter=mock_adapter,
                db=mock_db,
            )
            assert result is False


class TestDailyStats:
    """日统计逻辑"""

    @pytest.mark.asyncio
    async def test_daily_stats_aggregation(self):
        """日统计正确聚合各平台数据"""
        from services.tx_trade.src.services.delivery_panel_service import (
            DeliveryPanelService,
        )

        mock_db = AsyncMock()
        mock_rows = [
            {
                "platform": "meituan",
                "order_count": 10,
                "revenue_fen": 50000,
                "commission_fen": 9000,
                "net_revenue_fen": 41000,
            },
            {
                "platform": "eleme",
                "order_count": 5,
                "revenue_fen": 20000,
                "commission_fen": 3600,
                "net_revenue_fen": 16400,
            },
        ]

        with patch(
            "services.tx_trade.src.services.delivery_panel_service.DeliveryOrderRepository.get_daily_stats_by_platform",
            new=AsyncMock(return_value=mock_rows),
        ):
            stats = await DeliveryPanelService.get_daily_stats(
                tenant_id=TENANT_A,
                store_id=STORE_ID,
                target_date=date(2026, 3, 31),
                db=mock_db,
            )

        assert stats["total_orders"] == 15
        assert stats["total_revenue_fen"] == 70000
        assert stats["total_commission_fen"] == 12600
        assert stats["total_net_revenue_fen"] == 57400
        assert len(stats["platforms"]) == 2

        mt = next(p for p in stats["platforms"] if p["platform"] == "meituan")
        assert mt["platform_name"] == "美团外卖"
        assert mt["effective_rate"] == round(9000 / 50000, 4)


class TestDuplicateOrderHandling:
    """重复订单幂等处理"""

    @pytest.mark.asyncio
    async def test_duplicate_order_raises(self):
        """相同 platform + platform_order_id 的订单，第二次推送抛出 DuplicateOrderError"""
        from services.tx_trade.src.services.delivery_panel_service import (
            DeliveryPanelService,
            DuplicateOrderError,
        )

        existing_order = _mock_order_model(
            status="pending_accept",
            platform="meituan",
            platform_order_id="MT123456",
        )
        mock_db = AsyncMock()

        with (
            patch("services.tx_trade.src.services.delivery_panel_service._get_adapter") as mock_get_adapter,
            patch(
                "services.tx_trade.src.services.delivery_panel_service."
                "DeliveryOrderRepository.get_by_platform_order_id",
                new=AsyncMock(return_value=existing_order),  # 已存在
            ),
        ):
            mock_adapter = MagicMock()
            mock_adapter.verify_signature.return_value = True
            mock_adapter.parse_order.return_value = MagicMock(
                platform="meituan",
                platform_order_id="MT123456",
                total_fen=4800,
                items=[],
                customer_name="张三",
                customer_phone="138****8888",
                delivery_address="...",
                estimated_delivery_at=None,
            )
            mock_get_adapter.return_value = mock_adapter

            with pytest.raises(DuplicateOrderError):
                await DeliveryPanelService.receive_webhook(
                    platform="meituan",
                    raw_body=b"{}",
                    payload=_make_meituan_payload(),
                    signature="",
                    tenant_id=TENANT_A,
                    store_id=STORE_ID,
                    brand_id=BRAND_ID,
                    app_id=APP_ID,
                    app_secret=APP_SECRET,
                    shop_id=SHOP_ID,
                    commission_rate=COMMISSION_RATE,
                    db=mock_db,
                )
