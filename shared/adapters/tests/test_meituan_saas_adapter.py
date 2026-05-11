"""美团 SAAS 适配器 top-level 测试（CH-02.7a a3 迁自 saas/tests/）

迁移内容：a1 baseline 25 passed 测试全集（4 类）：
  - TestMeituanSaasAdapterInit（2）— init 成功 / 缺凭据失败
  - TestWebhookSignatureVerification（4）— sign 算法 + authenticate
  - TestReservationMixin（3）— MeituanReservationMixin 4 方法
  - TestOrderManagement::test_query_order_requires_id_or_seq（1）
  - TestFoodManagement（3）— query / update_stock / sold_out
  - TestMeituanErrorHandling（7）— handle_error + 网络异常
  - TestMeituanAdapterInit（4）— 凭据/默认 URL/POI
  - TestAsyncResourceManagement（1）— close 释放

不迁移：a1 baseline 24 pre-existing failed（to_order/to_staff_action dead code
+ TestOrderManagement.api_client 几个 mock 错位）— 走决策 79 独立 follow-up
issue 跟踪（schemas 模块全 repo 不存在；api_client.* 与 client.* mock 错配）。
"""

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from shared.adapters.meituan_saas_adapter import (
    MeituanReservationMixin,
    MeituanSaasAdapter,
)


@pytest.fixture
def adapter():
    config = {
        "base_url": "https://waimaiopen.meituan.com",
        "app_key": "test_app_key",
        "app_secret": "test_app_secret",
        "poi_id": "12345678",
        "timeout": 5,
        "retry_times": 1,
    }
    return MeituanSaasAdapter(config)


def _mock_response(json_data, status_code=200):
    """构造模拟的 httpx.Response"""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = json_data
    response.raise_for_status = MagicMock()
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=response,
        )
    return response


# ============================================================
# 初始化
# ============================================================


class TestMeituanSaasAdapterInit:
    def test_init_success(self, adapter):
        assert adapter.app_key == "test_app_key"
        assert adapter.app_secret == "test_app_secret"
        assert adapter.poi_id == "12345678"

    def test_init_missing_credentials(self):
        with pytest.raises(ValueError, match="app_key和app_secret不能为空"):
            MeituanSaasAdapter({"base_url": "https://waimaiopen.meituan.com"})

    def test_init_missing_app_key(self):
        """缺少app_key时抛出ValueError"""
        with pytest.raises(ValueError, match="app_key和app_secret不能为空"):
            MeituanSaasAdapter(
                {
                    "base_url": "https://waimaiopen.meituan.com",
                    "app_secret": "secret",
                }
            )

    def test_init_missing_app_secret(self):
        """缺少app_secret时抛出ValueError"""
        with pytest.raises(ValueError, match="app_key和app_secret不能为空"):
            MeituanSaasAdapter(
                {
                    "base_url": "https://waimaiopen.meituan.com",
                    "app_key": "key",
                }
            )

    def test_init_default_base_url(self):
        """未指定base_url时使用默认美团地址"""
        adapter = MeituanSaasAdapter(
            {
                "app_key": "k",
                "app_secret": "s",
            }
        )
        assert adapter.base_url == "https://waimaiopen.meituan.com"

    def test_init_custom_poi_id(self):
        """自定义门店ID"""
        adapter = MeituanSaasAdapter(
            {
                "app_key": "k",
                "app_secret": "s",
                "poi_id": "CUSTOM_POI",
            }
        )
        assert adapter.poi_id == "CUSTOM_POI"


# ============================================================
# Webhook 签名验证
# ============================================================


class TestWebhookSignatureVerification:
    """Webhook 接收签名验证测试"""

    def test_generate_sign_deterministic(self, adapter):
        """签名生成是确定性的"""
        params = {"order_id": "MT001", "status": "4"}
        sign1 = adapter._generate_sign(params)
        sign2 = adapter._generate_sign(params)
        assert sign1 == sign2

    def test_generate_sign_format(self, adapter):
        """签名格式为32位小写MD5"""
        params = {"order_id": "MT001"}
        sign = adapter._generate_sign(params)
        assert len(sign) == 32
        assert sign == sign.lower()
        assert all(c in "0123456789abcdef" for c in sign)

    def test_generate_sign_includes_secret(self, adapter):
        """不同app_secret生成不同签名"""
        params = {"order_id": "MT001"}
        sign1 = adapter._generate_sign(params)

        adapter2 = MeituanSaasAdapter(
            {
                "base_url": "https://waimaiopen.meituan.com",
                "app_key": "test_app_key",
                "app_secret": "different_secret",
                "poi_id": "12345678",
            }
        )
        sign2 = adapter2._generate_sign(params)
        assert sign1 != sign2

    def test_authenticate_adds_sign_and_app_key(self, adapter):
        """authenticate 方法添加 app_key, timestamp, sign"""
        result = adapter.authenticate({"order_id": "MT001"})
        assert "app_key" in result
        assert "timestamp" in result
        assert "sign" in result
        assert result["app_key"] == "test_app_key"
        assert result["order_id"] == "MT001"


# ============================================================
# 预订（MeituanReservationMixin）
# ============================================================


class TestReservationMixin:
    """预订数据处理测试（MeituanReservationMixin）"""

    @pytest.mark.asyncio
    async def test_query_reservation_detail(self):
        """验证预订详情查询"""

        class TestableAdapter(MeituanReservationMixin, MeituanSaasAdapter):
            pass

        mixed = TestableAdapter(
            {
                "base_url": "https://waimaiopen.meituan.com",
                "app_key": "test_key",
                "app_secret": "test_secret",
                "poi_id": "P001",
            }
        )

        mock_data = {
            "code": "ok",
            "data": {
                "reservation_id": "RSV001",
                "guest_name": "张先生",
                "guest_count": 4,
                "arrival_time": "2024-03-01 18:00:00",
                "status": "confirmed",
                "table_type": "大桌",
            },
        }
        mixed.client.get = AsyncMock(return_value=_mock_response(mock_data))

        result = await mixed.query_reservation(external_reservation_id="RSV001")

        assert result["data"]["reservation_id"] == "RSV001"
        assert result["data"]["guest_count"] == 4
        assert result["data"]["status"] == "confirmed"

    @pytest.mark.asyncio
    async def test_confirm_reservation(self):
        """验证预订确认操作"""

        class TestableAdapter(MeituanReservationMixin, MeituanSaasAdapter):
            pass

        mixed = TestableAdapter(
            {
                "base_url": "https://waimaiopen.meituan.com",
                "app_key": "test_key",
                "app_secret": "test_secret",
                "poi_id": "P001",
            }
        )

        mock_data = {"code": "ok", "data": {"reservation_id": "RSV001", "status": "confirmed"}}
        mixed.client.post = AsyncMock(return_value=_mock_response(mock_data))

        result = await mixed.confirm_reservation(external_reservation_id="RSV001")

        assert result["data"]["status"] == "confirmed"

    @pytest.mark.asyncio
    async def test_cancel_reservation_with_reason(self):
        """验证带原因的预订取消"""

        class TestableAdapter(MeituanReservationMixin, MeituanSaasAdapter):
            pass

        mixed = TestableAdapter(
            {
                "base_url": "https://waimaiopen.meituan.com",
                "app_key": "test_key",
                "app_secret": "test_secret",
                "poi_id": "P001",
            }
        )

        mock_data = {"code": "ok", "data": {"reservation_id": "RSV001", "status": "cancelled"}}
        mixed.client.post = AsyncMock(return_value=_mock_response(mock_data))

        result = await mixed.cancel_reservation(
            external_reservation_id="RSV001",
            reason="顾客临时有事",
        )

        assert result["data"]["status"] == "cancelled"
        call_kwargs = mixed.client.post.call_args
        sent_data = call_kwargs.kwargs.get("data", call_kwargs[1].get("data", {}))
        assert sent_data["reason"] == "顾客临时有事"


# ============================================================
# 订单管理
# ============================================================


class TestOrderManagement:
    """订单管理接口测试

    #434 第 2 项 — query/confirm/cancel 三方法走 `self.api_client.*` 路径，
    a1 baseline 24 pre-existing failed 中 3 个（test_query_order_by_id /
    test_confirm_order / test_cancel_order）因 mock 错位（mock `adapter.client.*`
    httpx 层而非 `adapter.api_client.*` MeituanClient 层）失败。本次补反测使用
    正确的 `adapter.api_client.<method>` mock。
    """

    @pytest.mark.asyncio
    async def test_query_order_requires_id_or_seq(self, adapter):
        """未提供order_id和day_seq时抛出ValueError"""
        with pytest.raises(ValueError, match="order_id和day_seq至少提供一个"):
            await adapter.query_order()

    @pytest.mark.asyncio
    async def test_query_order_by_id(self, adapter):
        """通过订单ID查询订单详情（走 api_client.query_order）"""
        mock_result = {
            "order_id": "MT001",
            "status": 4,
            "total_price": 8800,
            "food_list": [
                {"food_id": "F001", "food_name": "宫保鸡丁", "count": 1, "price": 3800},
            ],
        }
        adapter.api_client.query_order = AsyncMock(return_value=mock_result)

        result = await adapter.query_order(order_id="MT001")

        adapter.api_client.query_order.assert_called_once_with("MT001")
        assert result["order_id"] == "MT001"
        assert result["status"] == 4
        assert result["total_price"] == 8800

    @pytest.mark.asyncio
    async def test_query_order_by_day_seq(self, adapter):
        """通过日流水号查询订单（order_id 缺省时 fallback 到 day_seq）"""
        mock_result = {"order_id": "MT002", "status": 1}
        adapter.api_client.query_order = AsyncMock(return_value=mock_result)

        result = await adapter.query_order(day_seq="20240301001")

        adapter.api_client.query_order.assert_called_once_with("20240301001")
        assert result["order_id"] == "MT002"

    @pytest.mark.asyncio
    async def test_confirm_order(self, adapter):
        """确认订单（走 api_client.confirm_order）"""
        mock_result = {"order_id": "MT001", "status": "confirmed"}
        adapter.api_client.confirm_order = AsyncMock(return_value=mock_result)

        result = await adapter.confirm_order(order_id="MT001")

        adapter.api_client.confirm_order.assert_called_once_with("MT001")
        assert result["status"] == "confirmed"

    @pytest.mark.asyncio
    async def test_cancel_order(self, adapter):
        """取消订单（走 api_client.cancel_order，含 reason_code + reason）"""
        mock_result = {"order_id": "MT001", "status": "cancelled"}
        adapter.api_client.cancel_order = AsyncMock(return_value=mock_result)

        result = await adapter.cancel_order(
            order_id="MT001",
            reason_code=1,
            reason="商家缺货",
        )

        adapter.api_client.cancel_order.assert_called_once_with("MT001", 1, "商家缺货")
        assert result["status"] == "cancelled"


# ============================================================
# 商品管理
# ============================================================


class TestFoodManagement:
    """商品管理接口测试"""

    @pytest.mark.asyncio
    async def test_query_food_list(self, adapter):
        """查询商品列表"""
        mock_data = {
            "code": "ok",
            "data": [
                {"food_id": "F001", "food_name": "宫保鸡丁", "price": 3800, "stock": 50},
                {"food_id": "F002", "food_name": "米饭", "price": 300, "stock": 200},
            ],
        }
        adapter.client.get = AsyncMock(return_value=_mock_response(mock_data))

        result = await adapter.query_food()

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["food_name"] == "宫保鸡丁"

    @pytest.mark.asyncio
    async def test_update_food_stock(self, adapter):
        """更新商品库存"""
        mock_data = {"code": "ok", "data": {"food_id": "F001", "stock": 30}}
        adapter.client.post = AsyncMock(return_value=_mock_response(mock_data))

        result = await adapter.update_food_stock(food_id="F001", stock=30)

        assert result["stock"] == 30

    @pytest.mark.asyncio
    async def test_sold_out_food(self, adapter):
        """商品售罄"""
        mock_data = {"code": "ok", "data": {"food_id": "F001", "status": "sold_out"}}
        adapter.client.post = AsyncMock(return_value=_mock_response(mock_data))

        result = await adapter.sold_out_food(food_id="F001")

        assert result["status"] == "sold_out"


# ============================================================
# 错误处理
# ============================================================


class TestMeituanErrorHandling:
    """错误处理测试"""

    def test_handle_error_code_ok(self, adapter):
        """code='ok' 不应抛异常"""
        adapter.handle_error({"code": "ok", "data": {}})

    def test_handle_error_code_zero(self, adapter):
        """code=0 不应抛异常"""
        adapter.handle_error({"code": 0, "data": {}})

    def test_handle_error_business_error(self, adapter):
        """业务错误码抛出异常"""
        with pytest.raises(Exception, match="美团API错误"):
            adapter.handle_error({"code": "invalid_param", "message": "参数错误"})

    def test_handle_error_with_numeric_code(self, adapter):
        """数字错误码"""
        with pytest.raises(Exception, match="美团API错误"):
            adapter.handle_error({"code": 40001, "message": "签名验证失败"})

    @pytest.mark.asyncio
    async def test_network_timeout(self, adapter):
        """网络超时"""
        adapter.client.get = AsyncMock(side_effect=httpx.ConnectTimeout("连接超时"))

        with pytest.raises(Exception):
            await adapter.query_order(order_id="MT001")

    @pytest.mark.asyncio
    async def test_http_500_error(self, adapter):
        """服务端500错误"""
        adapter.client.post = AsyncMock(
            return_value=_mock_response({"error": "Internal Server Error"}, status_code=500)
        )

        with pytest.raises(Exception):
            await adapter.confirm_order(order_id="MT001")

    @pytest.mark.asyncio
    async def test_malformed_json_response(self, adapter):
        """响应非JSON格式"""
        response = MagicMock(spec=httpx.Response)
        response.status_code = 200
        response.raise_for_status = MagicMock()
        response.json.side_effect = ValueError("Invalid JSON")
        adapter.client.get = AsyncMock(return_value=response)

        with pytest.raises(Exception):
            await adapter.query_order(order_id="MT001")


# ============================================================
# 异步资源管理
# ============================================================


class TestAsyncResourceManagement:
    """异步资源管理测试"""

    @pytest.mark.asyncio
    async def test_close_releases_client(self, adapter):
        """close() 正确释放资源"""
        adapter.client.aclose = AsyncMock()
        await adapter.close()
        adapter.client.aclose.assert_called_once()
