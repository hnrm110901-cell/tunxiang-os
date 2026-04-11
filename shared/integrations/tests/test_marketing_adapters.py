"""营销渠道适配器测试 — 微信/美团/抖音

覆盖 Mock 模式下的核心功能，确保所有适配器在无凭据时优雅降级。
"""
from __future__ import annotations

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# 微信公众号 + 企微 适配器测试
# ─────────────────────────────────────────────────────────────────────────────

class TestWeChatOAService:
    """WeChatOAService Mock 模式测试"""

    @pytest.fixture
    def service(self):
        from shared.integrations.wechat_marketing import WeChatOAService
        return WeChatOAService()

    def test_mock_mode_when_no_credentials(self, service) -> None:
        """未配置凭据时进入 mock 模式"""
        assert service.is_mock is True

    @pytest.mark.asyncio
    async def test_send_template_msg_mock(self, service) -> None:
        """Mock 模式下发送模板消息返回 mock 状态"""
        result = await service.send_template_msg(
            openid="oXyz1234abcdefgh",
            template_id="mock_tpl_id",
            data={"keyword1": {"value": "测试内容"}},
        )
        assert result["status"] == "mock"
        assert "msg_id" in result
        assert "oa_" in result["msg_id"]

    @pytest.mark.asyncio
    async def test_send_marketing_notification_mock(self, service) -> None:
        """营销通知 mock 模式"""
        result = await service.send_marketing_notification(
            openid="oXyz1234abcdefgh",
            title="新品上市",
            content="招牌麻辣香锅新品来啦",
            remark="仅限本周",
        )
        assert result["status"] in ("mock", "skipped")

    @pytest.mark.asyncio
    async def test_openid_masking(self, service) -> None:
        """openid 脱敏正确"""
        from shared.integrations.wechat_marketing import _mask_openid
        masked = _mask_openid("oXyz12345678abcd")
        assert "****" in masked
        assert len(masked) <= 20

    @pytest.mark.asyncio
    async def test_send_order_notification_mock(self, service) -> None:
        """订单通知 mock 发送"""
        result = await service.send_order_notification(
            openid="oXyz12345678abcd",
            order_no="ORD20260411001",
            store_name="测试餐厅",
            status="已完成",
            amount_yuan="88.00",
        )
        assert result["status"] == "mock"


class TestWeComService:
    """WeComService Mock 模式测试"""

    @pytest.fixture
    def service(self):
        from shared.integrations.wechat_marketing import WeComService
        return WeComService()

    def test_mock_mode_when_no_credentials(self, service) -> None:
        assert service.is_mock is True

    @pytest.mark.asyncio
    async def test_send_text_to_customer_mock(self, service) -> None:
        result = await service.send_text_to_customer(
            chat_type="single",
            chat_id_list=["EXTERN_ID_001", "EXTERN_ID_002"],
            text_content="好久不见！我们有新品上架，欢迎来体验～",
        )
        assert result["status"] == "mock"
        assert result["fail_list"] == []

    @pytest.mark.asyncio
    async def test_send_miniprogram_mock(self, service) -> None:
        result = await service.send_miniprogram_to_customer(
            external_userid_list=["EXTERN_ID_001"],
            miniprogram_appid="wx1234567890abcdef",
            page="pages/menu/index",
            title="查看本周新品菜单",
        )
        assert result["status"] == "mock"

    @pytest.mark.asyncio
    async def test_agent_message_mock(self, service) -> None:
        result = await service.send_agent_message(
            user_ids=["manager001", "manager002"],
            content="营销 Agent 提醒：今日复购率下降 15%，建议启动唤醒旅程",
        )
        assert result["status"] == "mock"


# ─────────────────────────────────────────────────────────────────────────────
# 美团营销适配器测试
# ─────────────────────────────────────────────────────────────────────────────

class TestMeituanMarketingAdapter:

    @pytest.fixture
    def adapter(self):
        from shared.integrations.meituan_marketing import MeituanMarketingAdapter
        return MeituanMarketingAdapter()

    def test_mock_mode(self, adapter) -> None:
        assert adapter.is_mock is True

    @pytest.mark.asyncio
    async def test_create_coupon_mock(self, adapter) -> None:
        result = await adapter.create_coupon(
            tenant_id="t-001",
            store_id="store-001",
            coupon_config={
                "name": "满50减10",
                "discount_fen": 1000,
                "min_order_fen": 5000,
                "total_count": 200,
                "per_limit": 1,
                "start_time": "2026-04-15T00:00:00Z",
                "end_time": "2026-04-22T23:59:59Z",
            },
        )
        assert result["status"] == "mock"
        assert "MOCK_CPT_" in result["coupon_id"]
        assert result["platform"] == "meituan"

    @pytest.mark.asyncio
    async def test_get_promotion_list_mock(self, adapter) -> None:
        result = await adapter.get_promotion_list("t-001", "store-001")
        assert result["total"] >= 0
        assert isinstance(result["items"], list)
        assert result["status"] == "mock"

    @pytest.mark.asyncio
    async def test_get_ad_spend_mock(self, adapter) -> None:
        result = await adapter.get_ad_spend_data("t-001", "store-001", "2026-04-01", "2026-04-11")
        assert "total_spend_fen" in result
        assert isinstance(result["total_spend_fen"], int)
        assert "roi" in result
        assert result["roi"] > 0

    @pytest.mark.asyncio
    async def test_get_order_attribution_mock(self, adapter) -> None:
        result = await adapter.get_order_attribution("t-001", "store-001", "2026-04-01", "2026-04-11")
        assert "total_orders" in result
        assert "attribution_breakdown" in result
        breakdown = result["attribution_breakdown"]
        assert "paid_ad" in breakdown
        assert "natural" in breakdown
        # 确认金额是整数（分）
        assert isinstance(breakdown["paid_ad"]["revenue_fen"], int)


# ─────────────────────────────────────────────────────────────────────────────
# 抖音营销适配器测试
# ─────────────────────────────────────────────────────────────────────────────

class TestDouyinMarketingAdapter:

    @pytest.fixture
    def adapter(self):
        from shared.integrations.douyin_marketing import DouyinMarketingAdapter
        return DouyinMarketingAdapter()

    def test_mock_mode(self, adapter) -> None:
        assert adapter.is_mock is True

    @pytest.mark.asyncio
    async def test_create_poi_activity_mock(self, adapter) -> None:
        result = await adapter.create_poi_activity(
            tenant_id="t-001",
            store_id="store-001",
            activity_config={
                "name": "超值双人套餐",
                "activity_type": "group_buy",
                "original_price_fen": 19800,
                "sale_price_fen": 12800,
                "total_stock": 100,
                "start_time": "2026-04-15T00:00:00Z",
                "end_time": "2026-05-15T23:59:59Z",
                "poi_id": "POI_12345",
            },
        )
        assert result["status"] == "mock"
        assert "MOCK_DY_" in result["activity_id"]
        assert result["platform"] == "douyin"

    @pytest.mark.asyncio
    async def test_get_content_performance_mock(self, adapter) -> None:
        result = await adapter.get_content_performance("t-001", "store-001", days=7)
        assert "total_views" in result
        assert "content_roi" in result
        assert result["content_roi"] > 0
        assert "top_creators" in result
        assert len(result["top_creators"]) >= 1

    @pytest.mark.asyncio
    async def test_get_ad_roi_mock(self, adapter) -> None:
        result = await adapter.get_ad_roi_data("t-001", "store-001")
        assert "total_spend_fen" in result
        assert "roi" in result
        assert isinstance(result["total_spend_fen"], int)

    @pytest.mark.asyncio
    async def test_sync_live_orders_mock(self, adapter) -> None:
        result = await adapter.sync_live_orders("t-001", "store-001")
        assert "synced_count" in result
        assert isinstance(result["orders"], list)
        assert result["platform"] == "douyin"

    @pytest.mark.asyncio
    async def test_get_store_traffic_mock(self, adapter) -> None:
        result = await adapter.get_store_traffic_data("t-001", "store-001", "2026-04-11")
        assert "total_visits" in result
        assert "douyin_attributed_visits" in result
        assert "source_breakdown" in result
        # 归因率应在 0-1 之间
        assert 0 <= result["attribution_rate"] <= 1.0
