"""
奥琦玮供应链适配器完整测试套件（从老项目迁移）
覆盖：正常数据拉取、认证失败处理、数据格式转换验证、边界条件
只mock HTTP请求层（httpx），不mock适配器内部逻辑

迁移说明：
- 源文件：tunxiang/packages/api-adapters/aoqiwei/tests/test_aoqiwei_adapter_full.py
- 移除了 core.exceptions 导入（新项目中不存在该模块）
- 更新了 sys.path 设置以适配新项目目录结构
- 适配器类名和方法签名保持一致，无需修改
"""
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.abspath(os.path.join(_here, "../../../.."))
_gateway_src = os.path.join(_repo_root, "apps", "api-gateway", "src")
if _gateway_src not in sys.path:
    sys.path.insert(0, _gateway_src)

import pytest
import httpx
from decimal import Decimal
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from src.adapter import AoqiweiAdapter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def adapter():
    """创建奥琦玮适配器实例"""
    config = {
        "base_url": "https://openapi.acescm.cn",
        "app_key": "test_key",
        "app_secret": "test_secret",
        "timeout": 5,
        "retry_times": 1,
    }
    return AoqiweiAdapter(config)


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


# ---------------------------------------------------------------------------
# 正常数据拉取路径
# ---------------------------------------------------------------------------

class TestAoqiweiFetchData:
    """正常数据拉取路径测试"""

    @pytest.mark.asyncio
    async def test_query_goods_returns_data(self, adapter):
        """验证货品查询返回正确数据"""
        mock_response_data = {
            "success": True,
            "code": 0,
            "msg": "成功",
            "data": {
                "list": [
                    {"goodCode": "G001", "goodName": "五花肉", "unit": "kg", "price": 3500},
                    {"goodCode": "G002", "goodName": "鸡蛋", "unit": "个", "price": 150},
                ],
                "total": 2,
            },
        }
        adapter._client.get = AsyncMock(return_value=_mock_response(mock_response_data))

        result = await adapter.query_goods(page=1, page_size=100)

        assert isinstance(result, dict)
        assert result["total"] == 2
        assert len(result["list"]) == 2
        assert result["list"][0]["goodCode"] == "G001"
        assert result["list"][0]["goodName"] == "五花肉"

    @pytest.mark.asyncio
    async def test_query_shops_returns_list(self, adapter):
        """验证门店列表查询"""
        mock_response_data = {
            "success": True,
            "code": 0,
            "data": [
                {"shopCode": "SH001", "shopName": "总店", "address": "长沙市岳麓区"},
                {"shopCode": "SH002", "shopName": "分店", "address": "长沙市天心区"},
            ],
        }
        adapter._client.get = AsyncMock(return_value=_mock_response(mock_response_data))

        result = await adapter.query_shops()

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["shopCode"] == "SH001"
        assert result[1]["shopName"] == "分店"

    @pytest.mark.asyncio
    async def test_query_purchase_orders_returns_data(self, adapter):
        """验证采购入库单查询"""
        mock_response_data = {
            "success": True,
            "code": 0,
            "data": {
                "list": [
                    {"orderNo": "PO001", "depotCode": "D001", "totalAmount": 50000},
                ],
                "total": 1,
            },
        }
        adapter._client.get = AsyncMock(return_value=_mock_response(mock_response_data))

        result = await adapter.query_purchase_orders(
            start_date="2024-01-01",
            end_date="2024-01-31",
        )

        assert result["total"] == 1
        assert result["list"][0]["orderNo"] == "PO001"

    @pytest.mark.asyncio
    async def test_query_delivery_dispatch_out(self, adapter):
        """验证配送出库单查询"""
        mock_response_data = {
            "success": True,
            "code": 0,
            "data": [
                {"orderNo": "DO001", "shopCode": "SH001", "status": "delivered"},
                {"orderNo": "DO002", "shopCode": "SH002", "status": "pending"},
            ],
        }
        adapter._client.get = AsyncMock(return_value=_mock_response(mock_response_data))

        result = await adapter.query_delivery_dispatch_out(
            start_date="2024-01-01",
            end_date="2024-01-31",
        )

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["orderNo"] == "DO001"


# ---------------------------------------------------------------------------
# 认证失败处理
# ---------------------------------------------------------------------------

class TestAuthenticationFailure:
    """认证失败处理测试"""

    @pytest.mark.asyncio
    async def test_invalid_appkey_raises_business_error(self, adapter):
        """appkey无效时，_request 抛出业务异常（query_goods 只捕获网络异常，业务异常透传）"""
        mock_response_data = {
            "success": False,
            "code": 40001,
            "msg": "appkey不存在或已过期",
        }
        adapter._client.get = AsyncMock(return_value=_mock_response(mock_response_data))

        with pytest.raises(Exception, match="奥琦玮API业务错误.*appkey不存在"):
            await adapter.query_goods()

    @pytest.mark.asyncio
    async def test_invalid_sign_raises_error(self, adapter):
        """签名错误时，_request 抛出业务异常（query_shops 只捕获网络异常，业务异常透传）"""
        mock_response_data = {
            "success": False,
            "code": 40002,
            "msg": "签名验证失败",
        }
        adapter._client.get = AsyncMock(return_value=_mock_response(mock_response_data))

        with pytest.raises(Exception, match="奥琦玮API业务错误.*签名验证失败"):
            await adapter.query_shops()

    @pytest.mark.asyncio
    async def test_http_401_raises_error(self, adapter):
        """HTTP 401认证失败时，query_goods 内部捕获并降级返回空结果"""
        adapter._client.get = AsyncMock(
            return_value=_mock_response({"error": "Unauthorized"}, status_code=401)
        )

        # query_goods 内部 try/except 捕获 HTTPStatusError，降级返回安全默认值
        result = await adapter.query_goods()
        assert result == {"list": [], "total": 0}

    def test_degraded_mode_init_without_credentials(self, monkeypatch):
        """未配置凭证时仍可初始化（降级模式）"""
        monkeypatch.delenv("AOQIWEI_APP_KEY", raising=False)
        monkeypatch.delenv("AOQIWEI_APP_SECRET", raising=False)
        adapter = AoqiweiAdapter({"base_url": "https://openapi.acescm.cn"})
        assert adapter.app_key == ""
        assert adapter.app_secret == ""


# ---------------------------------------------------------------------------
# 数据格式转换验证
# ---------------------------------------------------------------------------

class TestDataFormatConversion:
    """数据格式转换验证"""

    def test_to_order_complete_mapping(self, adapter):
        """验证完整订单数据映射"""
        raw = {
            "orderId": "AQ20240301001",
            "orderNo": "AQ-2024-0301-001",
            "orderDate": "2024-03-01 12:30:00",
            "orderStatus": "2",
            "shopCode": "SH001",
            "tableNo": "A05",
            "memberId": "VIP001",
            "totalAmount": 25600,
            "discountAmount": 3000,
            "remark": "多放辣",
            "waiterId": "W001",
            "items": [
                {"orderItemNo": "I001", "goodCode": "G001", "goodName": "剁椒鱼头", "qty": 1, "price": 12800},
                {"orderItemNo": "I002", "goodCode": "G002", "goodName": "蒜蓉西兰花", "qty": 2, "price": 3200},
            ],
        }

        order = adapter.to_order(raw, store_id="STORE_01", brand_id="BRAND_XJ")

        assert order.order_id == "AQ20240301001"
        assert order.order_number == "AQ-2024-0301-001"
        assert order.store_id == "STORE_01"
        assert order.brand_id == "BRAND_XJ"
        assert order.total == Decimal("256.00")
        assert order.discount == Decimal("30.00")
        assert order.table_number == "A05"
        assert order.customer_id == "VIP001"
        assert order.notes == "多放辣"
        assert len(order.items) == 2
        assert order.items[0].dish_name == "剁椒鱼头"
        assert order.items[0].unit_price == Decimal("128.00")
        assert order.items[1].quantity == 2
        assert order.items[1].subtotal == Decimal("64.00")

    def test_to_order_status_mapping(self, adapter):
        """验证各种状态码的映射"""
        from schemas.restaurant_standard_schema import OrderStatus

        base_raw = {
            "orderId": "A1", "orderNo": "N1",
            "totalAmount": 1000, "discountAmount": 0, "items": [],
        }

        for status_str, expected in [
            ("0", OrderStatus.PENDING),
            ("1", OrderStatus.CONFIRMED),
            ("2", OrderStatus.COMPLETED),
            ("3", OrderStatus.CANCELLED),
        ]:
            raw = {**base_raw, "orderStatus": status_str}
            order = adapter.to_order(raw, "S1", "B1")
            assert order.order_status == expected, f"status '{status_str}' 应映射为 {expected}"

    def test_to_order_empty_items(self, adapter):
        """没有订单项时items为空列表"""
        raw = {
            "orderId": "AQ_EMPTY",
            "orderNo": "AQ-EMPTY-001",
            "orderDate": "2024-01-01 12:00:00",
            "orderStatus": "2",
            "totalAmount": 10000,
            "discountAmount": 0,
            "items": [],
        }
        order = adapter.to_order(raw, "S1", "B1")
        assert order.items == []
        assert order.total == Decimal("100.00")

    def test_to_staff_action_complete_mapping(self, adapter):
        """验证完整操作数据映射"""
        raw = {
            "actionType": "refund",
            "operatorId": "OP_001",
            "amount": 5000,
            "reason": "菜品质量问题",
            "approvedBy": "MGR_001",
            "actionTime": "2024-03-01 14:30:00",
        }
        action = adapter.to_staff_action(raw, "STORE_01", "BRAND_XJ")

        assert action.action_type == "refund"
        assert action.operator_id == "OP_001"
        assert action.amount == Decimal("50.00")
        assert action.reason == "菜品质量问题"
        assert action.approved_by == "MGR_001"
        assert action.store_id == "STORE_01"
        assert action.brand_id == "BRAND_XJ"
        assert isinstance(action.created_at, datetime)


# ---------------------------------------------------------------------------
# 签名和参数构建测试
# ---------------------------------------------------------------------------

class TestSignAndParams:
    """签名和参数构建测试"""

    def test_sign_includes_app_secret(self, adapter):
        """签名计算中包含 app_secret"""
        params1 = {"a": "1"}
        sign1 = adapter._sign(params1)

        adapter2 = AoqiweiAdapter({
            "base_url": "https://openapi.acescm.cn",
            "app_key": "test_key",
            "app_secret": "different_secret",
        })
        sign2 = adapter2._sign(params1)

        assert sign1 != sign2

    def test_build_params_includes_appkey_and_sign(self, adapter):
        """_build_params 返回中包含 appkey, front, sign"""
        result = adapter._build_params({"shopCode": "SH001"})
        assert "appkey" in result
        assert "front" in result
        assert "sign" in result
        assert result["appkey"] == "test_key"

    def test_build_params_sign_is_32_chars(self, adapter):
        """签名长度为32位MD5"""
        result = adapter._build_params({"test": "value"})
        assert len(result["sign"]) == 32


# ---------------------------------------------------------------------------
# 参数校验
# ---------------------------------------------------------------------------

class TestParameterValidation:
    """参数校验测试"""

    @pytest.mark.asyncio
    async def test_query_goods_invalid_page_size(self, adapter):
        """page_size超出范围时抛出ValueError"""
        with pytest.raises(ValueError, match="page_size"):
            await adapter.query_goods(page_size=1000)

    @pytest.mark.asyncio
    async def test_query_goods_invalid_page(self, adapter):
        """page < 1 时抛出ValueError"""
        with pytest.raises(ValueError, match="page"):
            await adapter.query_goods(page=0)

    @pytest.mark.asyncio
    async def test_query_purchase_orders_bad_date(self, adapter):
        """日期格式错误时抛出ValueError"""
        with pytest.raises(ValueError, match="格式错误"):
            await adapter.query_purchase_orders(
                start_date="20240101",
                end_date="2024-01-31",
            )

    @pytest.mark.asyncio
    async def test_stock_estimate_validates_dates(self, adapter):
        """库存预估接口校验日期格式"""
        with pytest.raises(ValueError, match="格式错误"):
            await adapter.query_stock_estimate(
                shop_code="SH001",
                start_date="2024/01/01",
                end_date="2024-01-31",
            )


# ---------------------------------------------------------------------------
# 网络错误和重试
# ---------------------------------------------------------------------------

class TestNetworkErrors:
    """网络错误测试"""

    @pytest.mark.asyncio
    async def test_connection_timeout_raises(self, adapter):
        """连接超时后，query_shops 内部捕获并降级返回空列表"""
        adapter._client.get = AsyncMock(
            side_effect=httpx.ConnectTimeout("连接超时")
        )

        # query_shops 内部 try/except 捕获重试耗尽后的异常，降级返回空列表
        result = await adapter.query_shops()
        assert result == []

    @pytest.mark.asyncio
    async def test_server_error_500(self, adapter):
        """服务端500错误时，query_shops 内部捕获并降级返回空列表"""
        adapter._client.get = AsyncMock(
            return_value=_mock_response({"error": "Internal Server Error"}, status_code=500)
        )

        # query_shops 内部 try/except 捕获 HTTPStatusError，降级返回空列表
        result = await adapter.query_shops()
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_response_from_shops(self, adapter):
        """门店查询返回空列表时不报错"""
        mock_response_data = {"success": True, "code": 0, "data": []}
        adapter._client.get = AsyncMock(return_value=_mock_response(mock_response_data))

        result = await adapter.query_shops()
        assert result == []

    @pytest.mark.asyncio
    async def test_query_stock_fallback_on_error(self, adapter):
        """库存查询失败时返回空列表"""
        adapter._client.get = AsyncMock(
            side_effect=httpx.ConnectTimeout("timeout")
        )

        result = await adapter.query_stock(depot_code="D001")
        assert result == []


# ---------------------------------------------------------------------------
# P1-1: 多门店Token隔离测试
# ---------------------------------------------------------------------------

class TestMultiStoreTokenIsolation:
    """验证不同门店/客户适配器的凭证隔离"""

    def test_different_app_keys_produce_different_signs(self):
        """不同app_key/app_secret的适配器生成不同签名"""
        adapter_a = AoqiweiAdapter({
            "base_url": "https://openapi.acescm.cn",
            "app_key": "key_xuji",
            "app_secret": "secret_xuji",
        })
        adapter_b = AoqiweiAdapter({
            "base_url": "https://openapi.acescm.cn",
            "app_key": "key_changzai",
            "app_secret": "secret_changzai",
        })

        params = {"shopCode": "SH001"}
        sign_a = adapter_a._sign(params)
        sign_b = adapter_b._sign(params)

        assert sign_a != sign_b

    def test_adapters_have_isolated_credentials(self):
        """两个适配器实例的凭证完全隔离"""
        adapter_a = AoqiweiAdapter({
            "base_url": "https://a.acescm.cn",
            "app_key": "key_a",
            "app_secret": "secret_a",
        })
        adapter_b = AoqiweiAdapter({
            "base_url": "https://b.acescm.cn",
            "app_key": "key_b",
            "app_secret": "secret_b",
        })

        assert adapter_a.app_key != adapter_b.app_key
        assert adapter_a.app_secret != adapter_b.app_secret
        assert adapter_a.base_url != adapter_b.base_url

    @pytest.mark.asyncio
    async def test_concurrent_fetch_different_stores(self):
        """两个门店同时拉取数据，结果互不干扰"""
        import asyncio

        adapter_a = AoqiweiAdapter({
            "base_url": "https://openapi.acescm.cn",
            "app_key": "key_a", "app_secret": "sec_a",
            "timeout": 5, "retry_times": 1,
        })
        adapter_b = AoqiweiAdapter({
            "base_url": "https://openapi.acescm.cn",
            "app_key": "key_b", "app_secret": "sec_b",
            "timeout": 5, "retry_times": 1,
        })

        response_a = {"success": True, "code": 0, "data": [{"shopCode": "SH_A", "shopName": "徐记总店"}]}
        response_b = {"success": True, "code": 0, "data": [{"shopCode": "SH_B", "shopName": "尝在一起"}]}

        adapter_a._client.get = AsyncMock(return_value=_mock_response(response_a))
        adapter_b._client.get = AsyncMock(return_value=_mock_response(response_b))

        result_a, result_b = await asyncio.gather(
            adapter_a.query_shops(),
            adapter_b.query_shops(),
        )

        assert result_a[0]["shopCode"] == "SH_A"
        assert result_b[0]["shopCode"] == "SH_B"

    def test_to_order_store_brand_injection_isolation(self, adapter):
        """to_order 不同 store_id/brand_id 参数不会互相污染"""
        raw = {
            "orderId": "ISO_AQ001", "orderNo": "ISO-001",
            "totalAmount": 5000, "discountAmount": 0,
            "orderStatus": "2", "items": [],
        }

        order_a = adapter.to_order(raw, store_id="XUJI_01", brand_id="XUJI")
        order_b = adapter.to_order(raw, store_id="CZ_01", brand_id="CHANGZAI")

        assert order_a.store_id == "XUJI_01"
        assert order_a.brand_id == "XUJI"
        assert order_b.store_id == "CZ_01"
        assert order_b.brand_id == "CHANGZAI"


# ---------------------------------------------------------------------------
# P1-1: 分页处理测试
# ---------------------------------------------------------------------------

class TestPaginationHandling:
    """分页查询处理测试"""

    @pytest.mark.asyncio
    async def test_query_goods_pagination_params(self, adapter):
        """验证分页参数正确传递到请求"""
        mock_response_data = {
            "success": True, "code": 0,
            "data": {"list": [{"goodCode": "G001"}], "total": 1},
        }
        adapter._client.get = AsyncMock(return_value=_mock_response(mock_response_data))

        result = await adapter.query_goods(page=3, page_size=50)

        assert result["total"] == 1
        call_kwargs = adapter._client.get.call_args
        sent_params = call_kwargs.kwargs.get("params", call_kwargs[1].get("params", {}))
        assert sent_params["page"] == 3
        assert sent_params["pageSize"] == 50

    @pytest.mark.asyncio
    async def test_query_purchase_orders_pagination(self, adapter):
        """采购入库单分页查询"""
        page1_data = {
            "success": True, "code": 0,
            "data": {
                "list": [{"orderNo": f"PO{i:03d}"} for i in range(1, 51)],
                "total": 80,
            },
        }
        adapter._client.get = AsyncMock(return_value=_mock_response(page1_data))

        result = await adapter.query_purchase_orders(
            start_date="2024-01-01",
            end_date="2024-01-31",
            page=1,
            page_size=50,
        )

        assert result["total"] == 80
        assert len(result["list"]) == 50

    @pytest.mark.asyncio
    async def test_empty_list_returns_empty_not_error(self, adapter):
        """返回空数据时正常返回空列表/字典，不报错"""
        mock_response_data = {
            "success": True, "code": 0,
            "data": {"list": [], "total": 0},
        }
        adapter._client.get = AsyncMock(return_value=_mock_response(mock_response_data))

        result = await adapter.query_goods()

        assert result["list"] == []
        assert result["total"] == 0


# ---------------------------------------------------------------------------
# P1-1: POST接口测试（配送/采购/POS上传）
# ---------------------------------------------------------------------------

class TestPostEndpoints:
    """POST类型接口测试"""

    @pytest.mark.asyncio
    async def test_create_delivery_apply_success(self, adapter):
        """配送申请单创建成功"""
        mock_response_data = {
            "success": True, "code": 0,
            "data": {"applyNo": "AP20240101001", "status": "submitted"},
        }
        adapter._client.post = AsyncMock(return_value=_mock_response(mock_response_data))

        result = await adapter.create_delivery_apply({
            "shopCode": "SH001",
            "items": [{"goodCode": "G001", "qty": 100}],
        })

        assert result["applyNo"] == "AP20240101001"

    @pytest.mark.asyncio
    async def test_pos_upload_order_success(self, adapter):
        """POS订单上传成功"""
        mock_response_data = {"success": True, "code": 0, "data": {"received": True}}
        adapter._client.post = AsyncMock(return_value=_mock_response(mock_response_data))

        result = await adapter.pos_upload_order({
            "orderNo": "POS20240101001",
            "shopCode": "SH001",
            "totalAmount": 15000,
        })

        assert result["received"] is True

    @pytest.mark.asyncio
    async def test_pos_day_done_success(self, adapter):
        """POS日结成功"""
        mock_response_data = {"success": True, "code": 0, "data": {"done": True}}
        adapter._client.post = AsyncMock(return_value=_mock_response(mock_response_data))

        result = await adapter.pos_day_done(shop_code="SH001", date="2024-01-01")

        assert result["done"] is True

    @pytest.mark.asyncio
    async def test_pos_upload_order_failure_degrades(self, adapter):
        """POS订单上传失败时降级返回失败状态"""
        adapter._client.post = AsyncMock(
            side_effect=httpx.ConnectTimeout("timeout")
        )

        result = await adapter.pos_upload_order({"orderNo": "FAIL001"})
        assert result["success"] is False
        assert "message" in result

    @pytest.mark.asyncio
    async def test_confirm_delivery_in_success(self, adapter):
        """配送入库确认成功"""
        mock_response_data = {"success": True, "code": 0, "data": {"confirmed": True}}
        adapter._client.post = AsyncMock(return_value=_mock_response(mock_response_data))

        result = await adapter.confirm_delivery_in({
            "orderNo": "DO001", "shopCode": "SH001",
        })

        assert result["confirmed"] is True


# ---------------------------------------------------------------------------
# P1-1: 报表接口测试
# ---------------------------------------------------------------------------

class TestReportEndpoints:
    """报表接口测试"""

    @pytest.mark.asyncio
    async def test_query_inventory_report_success(self, adapter):
        """进销存报表查询成功"""
        mock_response_data = {
            "success": True, "code": 0,
            "data": {
                "list": [
                    {"goodCode": "G001", "beginQty": 100, "inQty": 50, "outQty": 30, "endQty": 120},
                ],
                "total": 1,
            },
        }
        adapter._client.get = AsyncMock(return_value=_mock_response(mock_response_data))

        result = await adapter.query_inventory_report(
            start_date="2024-01-01",
            end_date="2024-01-31",
        )

        assert result["total"] == 1
        assert result["list"][0]["endQty"] == 120

    @pytest.mark.asyncio
    async def test_query_inventory_report_fallback_on_error(self, adapter):
        """进销存报表查询失败时降级返回空"""
        adapter._client.get = AsyncMock(
            side_effect=httpx.ConnectTimeout("timeout")
        )

        result = await adapter.query_inventory_report(
            start_date="2024-01-01",
            end_date="2024-01-31",
        )

        assert result == {"list": [], "total": 0}

    @pytest.mark.asyncio
    async def test_good_diff_analysis_success(self, adapter):
        """货品差异分析查询成功"""
        mock_response_data = {
            "success": True, "code": 0,
            "data": {"list": [{"goodCode": "G001", "diffQty": -5}]},
        }
        adapter._client.get = AsyncMock(return_value=_mock_response(mock_response_data))

        result = await adapter.query_good_diff_analysis(
            start_date="2024-01-01",
            end_date="2024-01-31",
        )

        assert result["list"][0]["diffQty"] == -5


# ---------------------------------------------------------------------------
# P1-1: to_order 边界场景补充
# ---------------------------------------------------------------------------

class TestToOrderEdgeCases:
    """to_order 边界场景补充测试"""

    def test_order_with_no_items_key(self, adapter):
        """原始数据缺少 items 字段时默认空列表"""
        raw = {
            "orderId": "NOITEMS",
            "orderNo": "NI-001",
            "orderStatus": "2",
            "totalAmount": 10000,
            "discountAmount": 0,
        }
        order = adapter.to_order(raw, "S1", "B1")
        assert order.items == []

    def test_order_subtotal_calculation(self, adapter):
        """subtotal = total + discount"""
        raw = {
            "orderId": "SUB001", "orderNo": "SUB-001",
            "orderStatus": "2",
            "totalAmount": 18000,
            "discountAmount": 2000,
            "items": [],
        }
        order = adapter.to_order(raw, "S1", "B1")
        assert order.subtotal == Decimal("200.00")  # (18000+2000)/100
        assert order.total == Decimal("180.00")
        assert order.discount == Decimal("20.00")

    def test_order_unknown_status_defaults_pending(self, adapter):
        """未知状态码默认映射为 PENDING"""
        from schemas.restaurant_standard_schema import OrderStatus
        raw = {
            "orderId": "UNK001", "orderNo": "UNK-001",
            "orderStatus": "99",
            "totalAmount": 5000, "discountAmount": 0, "items": [],
        }
        order = adapter.to_order(raw, "S1", "B1")
        assert order.order_status == OrderStatus.PENDING

    def test_item_quantity_fallback(self, adapter):
        """订单项缺少 qty 时使用 quantity 字段"""
        raw = {
            "orderId": "QTY001", "orderNo": "QTY-001",
            "orderStatus": "2",
            "totalAmount": 5000, "discountAmount": 0,
            "items": [
                {"goodCode": "G001", "goodName": "菜A", "quantity": 3, "price": 5000},
            ],
        }
        order = adapter.to_order(raw, "S1", "B1")
        assert order.items[0].quantity == 3

    def test_item_special_requirements(self, adapter):
        """订单项备注映射到 special_requirements"""
        raw = {
            "orderId": "RMK001", "orderNo": "RMK-001",
            "orderStatus": "2",
            "totalAmount": 5000, "discountAmount": 0,
            "items": [
                {"goodCode": "G001", "goodName": "菜A", "qty": 1, "price": 5000, "remark": "不要葱"},
            ],
        }
        order = adapter.to_order(raw, "S1", "B1")
        assert order.items[0].special_requirements == "不要葱"


# ---------------------------------------------------------------------------
# P1-1: 异步资源管理测试
# ---------------------------------------------------------------------------

class TestAsyncResourceManagement:
    """异步资源管理测试"""

    @pytest.mark.asyncio
    async def test_aclose_releases_client(self, adapter):
        """aclose() 释放 HTTP 客户端"""
        adapter._client.aclose = AsyncMock()
        await adapter.aclose()
        adapter._client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_aexit_calls_aclose(self, adapter):
        """__aexit__ 调用 aclose"""
        adapter._client.aclose = AsyncMock()
        await adapter.__aexit__(None, None, None)
        adapter._client.aclose.assert_called_once()
