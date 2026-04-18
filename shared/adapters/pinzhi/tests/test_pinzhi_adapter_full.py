"""
品智POS适配器完整测试套件（从老项目迁移）
覆盖：正常路径、边界条件、错误处理、多门店隔离
只mock HTTP请求层（httpx），不mock适配器内部逻辑

迁移说明：
- 源文件：tunxiang/packages/api-adapters/pinzhi/tests/test_pinzhi_adapter_full.py
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
from unittest.mock import AsyncMock, patch, MagicMock

from src.adapter import PinzhiAdapter
from src.signature import generate_sign


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def adapter():
    """创建品智适配器实例"""
    config = {
        "base_url": "http://192.168.1.100:8080/pzcatering-gateway",
        "token": "test_token_12345",
        "timeout": 5,
        "retry_times": 1,  # 测试中只重试1次，加速
    }
    return PinzhiAdapter(config)


@pytest.fixture
def adapter_store_a():
    """门店A适配器（用于多门店隔离测试）"""
    return PinzhiAdapter({
        "base_url": "http://192.168.1.100:8080/pzcatering-gateway",
        "token": "token_store_a",
        "timeout": 5,
        "retry_times": 1,
    })


@pytest.fixture
def adapter_store_b():
    """门店B适配器（用于多门店隔离测试）"""
    return PinzhiAdapter({
        "base_url": "http://192.168.1.100:8080/pzcatering-gateway",
        "token": "token_store_b",
        "timeout": 5,
        "retry_times": 1,
    })


def _mock_response(json_data, status_code=200):
    """构造一个模拟的 httpx.Response"""
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
# 正常路径
# ---------------------------------------------------------------------------

class TestPinzhiAdapterFetchOrders:
    """验证订单数据拉取后格式正确"""

    @pytest.mark.asyncio
    async def test_fetch_orders_returns_normalized_data(self, adapter):
        """验证订单数据拉取后格式正确"""
        mock_api_response = {
            "success": 0,
            "res": [
                {
                    "billId": "B001",
                    "billNo": "20240101001",
                    "billStatus": 1,
                    "orderSource": 1,
                    "tableNo": "A01",
                    "openTime": "2024-01-01 12:00:00",
                    "payTime": "2024-01-01 13:00:00",
                    "dishPriceTotal": 15000,
                    "specialOfferPrice": 1000,
                    "realPrice": 14000,
                    "teaPrice": 200,
                },
                {
                    "billId": "B002",
                    "billNo": "20240101002",
                    "billStatus": 0,
                    "orderSource": 1,
                    "tableNo": "A02",
                    "openTime": "2024-01-01 12:30:00",
                    "dishPriceTotal": 8800,
                    "specialOfferPrice": 0,
                    "realPrice": 8800,
                    "teaPrice": 0,
                },
            ],
        }
        adapter.client.post = AsyncMock(return_value=_mock_response(mock_api_response))

        result = await adapter.query_orders(ognid="OGN001", business_date="2024-01-01")

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["billId"] == "B001"
        assert result[0]["billNo"] == "20240101001"
        assert result[0]["billStatus"] == 1
        assert result[1]["billId"] == "B002"

    @pytest.mark.asyncio
    async def test_fetch_orders_pagination_params(self, adapter):
        """验证分页参数正确传递"""
        mock_api_response = {"success": 0, "res": [{"billId": "B010"}]}
        adapter.client.post = AsyncMock(return_value=_mock_response(mock_api_response))

        result = await adapter.query_orders(
            ognid="OGN001",
            business_date="2024-01-01",
            page_index=3,
            page_size=50,
        )

        assert len(result) == 1
        # 验证请求中确实包含分页参数
        call_kwargs = adapter.client.post.call_args
        sent_data = call_kwargs.kwargs.get("data", call_kwargs[1].get("data", {}))
        assert sent_data["pageIndex"] == 3
        assert sent_data["pageSize"] == 50


class TestPinzhiAdapterFetchMenuItems:
    """验证菜品数据映射到统一模型"""

    @pytest.mark.asyncio
    async def test_fetch_menu_items_maps_correctly(self, adapter):
        """验证菜品数据拉取和字段映射"""
        mock_response_data = {
            "success": 0,
            "data": [
                {
                    "dishesId": "D001",
                    "dishesName": "红烧肉",
                    "dishPrice": 8800,
                    "rcId": "CAT01",
                    "rcName": "热菜",
                    "unit": "份",
                    "status": 1,
                },
                {
                    "dishesId": "D002",
                    "dishesName": "清蒸鲈鱼",
                    "dishPrice": 12800,
                    "rcId": "CAT01",
                    "rcName": "热菜",
                    "unit": "份",
                    "status": 1,
                },
            ],
        }
        # get_dishes 尝试多个路径，mock POST 和 GET
        adapter.client.post = AsyncMock(return_value=_mock_response(mock_response_data))
        adapter.client.get = AsyncMock(return_value=_mock_response(mock_response_data))

        result = await adapter.get_dishes(updatetime=0)

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["dishesId"] == "D001"
        assert result[0]["dishesName"] == "红烧肉"
        assert result[0]["dishPrice"] == 8800
        assert result[1]["dishesName"] == "清蒸鲈鱼"

    @pytest.mark.asyncio
    async def test_fetch_dish_categories(self, adapter):
        """验证菜品类别数据拉取"""
        mock_response_data = {
            "success": 0,
            "data": [
                {"rcId": "CAT01", "rcNAME": "热菜", "fatherId": "0"},
                {"rcId": "CAT02", "rcNAME": "凉菜", "fatherId": "0"},
                {"rcId": "CAT03", "rcNAME": "汤品", "fatherId": "0"},
            ],
        }
        adapter.client.get = AsyncMock(return_value=_mock_response(mock_response_data))

        result = await adapter.get_dish_categories()

        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0]["rcId"] == "CAT01"
        assert result[0]["rcNAME"] == "热菜"


class TestMultiStoreTokenIsolation:
    """验证不同门店使用各自的token，不混用"""

    @pytest.mark.asyncio
    async def test_multi_store_token_isolation(self, adapter_store_a, adapter_store_b):
        """验证不同门店适配器使用各自的token生成不同签名"""
        params = {"ognid": "shared_param"}

        signed_a = adapter_store_a._add_sign(params.copy())
        signed_b = adapter_store_b._add_sign(params.copy())

        # 不同token应该生成不同签名
        assert signed_a["sign"] != signed_b["sign"]
        # 验证签名是基于各自token生成的
        expected_sign_a = generate_sign("token_store_a", {"ognid": "shared_param"})
        expected_sign_b = generate_sign("token_store_b", {"ognid": "shared_param"})
        assert signed_a["sign"] == expected_sign_a
        assert signed_b["sign"] == expected_sign_b

    def test_adapters_have_different_tokens(self, adapter_store_a, adapter_store_b):
        """验证两个适配器实例的token完全隔离"""
        assert adapter_store_a.token == "token_store_a"
        assert adapter_store_b.token == "token_store_b"
        assert adapter_store_a.token != adapter_store_b.token


# ---------------------------------------------------------------------------
# 边界条件
# ---------------------------------------------------------------------------

class TestBoundaryConditions:
    """边界条件测试"""

    @pytest.mark.asyncio
    async def test_empty_response_returns_empty_list(self, adapter):
        """POS返回空数据时返回空列表，不报错"""
        mock_response_data = {"success": 0, "res": []}
        adapter.client.post = AsyncMock(return_value=_mock_response(mock_response_data))

        result = await adapter.query_orders(ognid="OGN001", business_date="2024-01-01")

        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_empty_dish_list_returns_empty(self, adapter):
        """菜品接口返回空列表"""
        mock_response_data = {"success": 0, "data": []}
        adapter.client.post = AsyncMock(return_value=_mock_response(mock_response_data))
        adapter.client.get = AsyncMock(return_value=_mock_response(mock_response_data))

        result = await adapter.get_dishes()

        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_handles_pagination(self, adapter):
        """大数据量分页处理：验证不同页返回不同数据"""
        page1_response = {
            "success": 0,
            "res": [{"billId": f"B{i:03d}"} for i in range(1, 21)],
        }
        page2_response = {
            "success": 0,
            "res": [{"billId": f"B{i:03d}"} for i in range(21, 31)],
        }

        call_count = 0
        async def mock_post(endpoint, **kwargs):
            nonlocal call_count
            call_count += 1
            data = kwargs.get("data", {})
            page_index = data.get("pageIndex", 1)
            if page_index == 1:
                return _mock_response(page1_response)
            else:
                return _mock_response(page2_response)

        adapter.client.post = mock_post

        result_page1 = await adapter.query_orders(
            ognid="OGN001", business_date="2024-01-01", page_index=1, page_size=20
        )
        result_page2 = await adapter.query_orders(
            ognid="OGN001", business_date="2024-01-01", page_index=2, page_size=20
        )

        assert len(result_page1) == 20
        assert len(result_page2) == 10
        assert result_page1[0]["billId"] == "B001"
        assert result_page2[0]["billId"] == "B021"

    @pytest.mark.asyncio
    async def test_missing_res_field_returns_empty(self, adapter):
        """API响应中缺少res字段时返回空列表"""
        mock_response_data = {"success": 0}
        adapter.client.post = AsyncMock(return_value=_mock_response(mock_response_data))

        result = await adapter.query_orders(ognid="OGN001", business_date="2024-01-01")

        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_store_info_empty_returns_empty_list(self, adapter):
        """门店信息接口返回空数据时"""
        mock_response_data = {"success": 0, "res": []}
        adapter.client.get = AsyncMock(return_value=_mock_response(mock_response_data))

        result = await adapter.get_store_info()

        assert result == []

    @pytest.mark.asyncio
    async def test_query_order_summary_empty(self, adapter):
        """收入数据为空时返回空字典"""
        mock_response_data = {"success": 0, "res": {}}
        adapter.client.get = AsyncMock(return_value=_mock_response(mock_response_data))

        result = await adapter.query_order_summary(ognid="OGN001", business_date="2024-01-01")

        assert isinstance(result, dict)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# 错误处理
# ---------------------------------------------------------------------------

class TestErrorHandling:
    """错误处理测试"""

    @pytest.mark.asyncio
    async def test_expired_token_raises_error(self, adapter):
        """Token过期时品智返回业务错误码，适配器应抛出异常"""
        mock_response_data = {
            "success": 1,
            "msg": "token已过期，请重新获取",
        }
        adapter.client.post = AsyncMock(return_value=_mock_response(mock_response_data))

        with pytest.raises(Exception, match="品智API错误.*token已过期"):
            await adapter.query_orders(ognid="OGN001", business_date="2024-01-01")

    @pytest.mark.asyncio
    async def test_errcode_style_error_raises(self, adapter):
        """品智errcode格式错误响应"""
        mock_response_data = {
            "errcode": 40001,
            "errmsg": "签名验证失败",
        }
        adapter.client.get = AsyncMock(return_value=_mock_response(mock_response_data))

        with pytest.raises(Exception, match="品智API错误.*签名验证失败"):
            await adapter.get_store_info()

    @pytest.mark.asyncio
    async def test_network_timeout_raises_error(self, adapter):
        """网络超时时抛出异常"""
        adapter.client.post = AsyncMock(
            side_effect=httpx.ConnectTimeout("连接超时")
        )

        with pytest.raises(Exception):
            await adapter.query_orders(ognid="OGN001", business_date="2024-01-01")

    @pytest.mark.asyncio
    async def test_http_500_raises_error(self, adapter):
        """服务端500错误"""
        adapter.client.post = AsyncMock(
            return_value=_mock_response({"error": "Internal Server Error"}, status_code=500)
        )

        with pytest.raises(Exception):
            await adapter.query_orders(ognid="OGN001", business_date="2024-01-01")

    @pytest.mark.asyncio
    async def test_malformed_response_raises_error(self, adapter):
        """POS返回非JSON格式数据时抛出异常"""
        response = MagicMock(spec=httpx.Response)
        response.status_code = 200
        response.raise_for_status = MagicMock()
        response.json.side_effect = ValueError("Invalid JSON")
        adapter.client.post = AsyncMock(return_value=response)

        with pytest.raises(Exception):
            await adapter.query_orders(ognid="OGN001", business_date="2024-01-01")

    @pytest.mark.asyncio
    async def test_api_rate_limit_handling(self, adapter):
        """API限流时适配器应正确传播异常"""
        mock_response_data = {
            "success": 429,
            "msg": "请求频率超限，请稍后重试",
        }
        adapter.client.get = AsyncMock(return_value=_mock_response(mock_response_data))

        with pytest.raises(Exception, match="品智API错误.*请求频率超限"):
            await adapter.get_store_info()

    def test_handle_error_success_response(self, adapter):
        """成功响应不应抛出异常"""
        adapter.handle_error({"success": 0, "msg": "成功", "res": []})

    def test_handle_error_errcode_zero_is_success(self, adapter):
        """errcode为0时不应抛出异常"""
        adapter.handle_error({"errcode": 0, "errmsg": "ok"})

    def test_handle_error_no_error_fields(self, adapter):
        """没有success和errcode字段时不应抛出异常"""
        adapter.handle_error({"data": [1, 2, 3]})


# ---------------------------------------------------------------------------
# to_order 映射测试补充
# ---------------------------------------------------------------------------

class TestToOrderEdgeCases:
    """to_order 边界场景测试"""

    def test_order_status_cancelled(self, adapter):
        """billStatus=2 映射为 CANCELLED"""
        from schemas.restaurant_standard_schema import OrderStatus
        raw = {
            "billId": "B999",
            "billNo": "CANCEL001",
            "billStatus": 2,
            "orderSource": 1,
            "dishPriceTotal": 0,
            "specialOfferPrice": 0,
            "realPrice": 0,
            "teaPrice": 0,
        }
        order = adapter.to_order(raw, store_id="S1", brand_id="BR1")
        assert order.order_status == OrderStatus.CANCELLED

    def test_order_status_pending(self, adapter):
        """billStatus=0 映射为 PENDING"""
        from schemas.restaurant_standard_schema import OrderStatus
        raw = {
            "billId": "B998",
            "billNo": "PEND001",
            "billStatus": 0,
            "orderSource": 1,
            "dishPriceTotal": 5000,
            "specialOfferPrice": 0,
            "realPrice": 5000,
            "teaPrice": 0,
        }
        order = adapter.to_order(raw, store_id="S1", brand_id="BR1")
        assert order.order_status == OrderStatus.PENDING

    def test_order_delivery_type(self, adapter):
        """orderSource != 1 映射为 DELIVERY"""
        from schemas.restaurant_standard_schema import OrderType
        raw = {
            "billId": "B997",
            "billNo": "DEL001",
            "billStatus": 1,
            "orderSource": 2,
            "dishPriceTotal": 3000,
            "specialOfferPrice": 0,
            "realPrice": 3000,
            "teaPrice": 0,
        }
        order = adapter.to_order(raw, store_id="S1", brand_id="BR1")
        assert order.order_type == OrderType.DELIVERY

    def test_order_without_dish_list(self, adapter):
        """没有 dishList 字段时 items 为空列表"""
        raw = {
            "billId": "B996",
            "billNo": "NODISH001",
            "billStatus": 1,
            "orderSource": 1,
            "dishPriceTotal": 10000,
            "specialOfferPrice": 0,
            "realPrice": 10000,
            "teaPrice": 0,
        }
        order = adapter.to_order(raw, store_id="S1", brand_id="BR1")
        assert order.items == []
        assert order.total == Decimal("100.00")

    def test_order_with_bad_open_time_fallback(self, adapter):
        """openTime格式异常时降级为当前时间"""
        raw = {
            "billId": "B995",
            "billNo": "BADTIME001",
            "billStatus": 1,
            "orderSource": 1,
            "openTime": "not-a-date",
            "dishPriceTotal": 1000,
            "specialOfferPrice": 0,
            "realPrice": 1000,
            "teaPrice": 0,
        }
        order = adapter.to_order(raw, store_id="S1", brand_id="BR1")
        assert isinstance(order.created_at, datetime)

    def test_order_item_subtotal_calculation(self, adapter):
        """验证菜品小计 = 单价 * 数量"""
        raw = {
            "billId": "B994",
            "billNo": "CALC001",
            "billStatus": 1,
            "orderSource": 1,
            "dishPriceTotal": 17600,
            "specialOfferPrice": 0,
            "realPrice": 17600,
            "teaPrice": 0,
            "dishList": [
                {"dishId": "D010", "dishName": "水煮鱼", "dishNum": 2, "dishPrice": 8800},
            ],
        }
        order = adapter.to_order(raw, store_id="S1", brand_id="BR1")
        assert order.items[0].unit_price == Decimal("88.00")
        assert order.items[0].quantity == 2
        assert order.items[0].subtotal == Decimal("176.00")


# ---------------------------------------------------------------------------
# 适配器初始化边界
# ---------------------------------------------------------------------------

class TestAdapterInitValidation:
    """适配器初始化校验"""

    def test_init_empty_base_url_raises(self):
        """base_url为空时抛出ValueError"""
        with pytest.raises(ValueError, match="base_url不能为空"):
            PinzhiAdapter({"token": "some_token"})

    def test_init_empty_token_raises(self):
        """token为空时抛出ValueError"""
        with pytest.raises(ValueError, match="token不能为空"):
            PinzhiAdapter({"base_url": "http://example.com"})

    def test_init_default_timeout(self):
        """未指定timeout使用默认值30"""
        adapter = PinzhiAdapter({
            "base_url": "http://example.com",
            "token": "t",
        })
        assert adapter.timeout == 30

    def test_init_default_retry_times(self):
        """未指定retry_times使用默认值3"""
        adapter = PinzhiAdapter({
            "base_url": "http://example.com",
            "token": "t",
        })
        assert adapter.retry_times == 3


# ---------------------------------------------------------------------------
# 签名功能测试补充
# ---------------------------------------------------------------------------

class TestSignatureIntegration:
    """签名在适配器中的集成测试"""

    def test_add_sign_includes_sign_key(self, adapter):
        """_add_sign 返回中包含 sign 字段"""
        result = adapter._add_sign({"ognid": "123"})
        assert "sign" in result
        assert len(result["sign"]) == 32

    def test_add_sign_preserves_original_params(self, adapter):
        """_add_sign 保留原始参数"""
        result = adapter._add_sign({"ognid": "123", "businessDate": "2024-01-01"})
        assert result["ognid"] == "123"
        assert result["businessDate"] == "2024-01-01"

    def test_sign_deterministic(self, adapter):
        """同一参数多次签名结果一致"""
        params = {"ognid": "123", "businessDate": "2024-01-01"}
        sign1 = adapter._add_sign(params.copy())["sign"]
        sign2 = adapter._add_sign(params.copy())["sign"]
        assert sign1 == sign2


# ---------------------------------------------------------------------------
# run_all_checks 测试
# ---------------------------------------------------------------------------

class TestRunAllChecks:
    """run_all_checks 综合检测接口测试"""

    @pytest.mark.asyncio
    async def test_run_all_checks_all_success(self, adapter):
        """所有接口检测成功"""
        success_response_list = {"success": 0, "res": [{"id": 1}]}
        success_response_data = {"success": 0, "data": [{"id": 1}]}

        adapter.client.get = AsyncMock(return_value=_mock_response(success_response_list))
        adapter.client.post = AsyncMock(return_value=_mock_response(success_response_data))

        results = await adapter.run_all_checks(
            business_date="2024-01-01", ognid="OGN001"
        )

        assert isinstance(results, list)
        assert len(results) > 0
        # 至少核心接口都应该成功
        core_results = [r for r in results if r["required"]]
        for r in core_results:
            assert r["ok"] is True, f"核心接口 {r['name']} 应该成功"

    @pytest.mark.asyncio
    async def test_run_all_checks_partial_failure(self, adapter):
        """部分接口失败时不影响其他接口检测"""
        call_count = 0

        async def mock_get(endpoint, **kwargs):
            nonlocal call_count
            call_count += 1
            if "queryTable" in endpoint:
                raise httpx.ConnectTimeout("timeout")
            return _mock_response({"success": 0, "res": [{"id": 1}]})

        adapter.client.get = mock_get
        adapter.client.post = AsyncMock(
            return_value=_mock_response({"success": 0, "res": [{"id": 1}]})
        )

        results = await adapter.run_all_checks(
            business_date="2024-01-01", ognid="OGN001"
        )

        # 应该有失败的项
        failed = [r for r in results if not r["ok"]]
        assert len(failed) >= 1
        # 其他接口应该还是成功的
        succeeded = [r for r in results if r["ok"]]
        assert len(succeeded) > 0


# ---------------------------------------------------------------------------
# 异步上下文管理器
# ---------------------------------------------------------------------------

class TestAsyncContextManager:
    """异步上下文管理器测试"""

    @pytest.mark.asyncio
    async def test_close_releases_client(self, adapter):
        """close() 调用后客户端应被关闭"""
        adapter.client.aclose = AsyncMock()
        await adapter.close()
        adapter.client.aclose.assert_called_once()


# ---------------------------------------------------------------------------
# P1-1: 菜品映射到屯象 Dish Model 测试
# ---------------------------------------------------------------------------

class TestFetchMenuItemsMapsToDishModel:
    """验证品智菜品通过 DishSync 映射到统一屯象 Dish 格式"""

    def test_basic_dish_mapping(self):
        """品智菜品字段正确映射到屯象标准格式"""
        from src.dish_sync import PinzhiDishSync

        raw = {
            "dishId": "D100",
            "dishName": "剁椒鱼头",
            "dishCode": "DCYT001",
            "categoryId": "CAT01",
            "categoryName": "热菜",
            "dishPrice": 12800,
            "costPrice": 4500,
            "memberPrice": 11500,
            "unit": "份",
            "status": 1,
            "isWeighing": 0,
            "isTemporary": 0,
            "dishImage": "https://img.example.com/dcyt.jpg",
            "dishDesc": "招牌剁椒鱼头",
            "sortOrder": 10,
        }

        result = PinzhiDishSync.map_to_tunxiang_dish(raw)

        assert result["dish_id"] == "D100"
        assert result["dish_name"] == "剁椒鱼头"
        assert result["dish_code"] == "DCYT001"
        assert result["category_id"] == "CAT01"
        assert result["category_name"] == "热菜"
        assert result["price_fen"] == 12800
        assert result["cost_fen"] == 4500
        assert result["member_price_fen"] == 11500
        assert result["unit"] == "份"
        assert result["status"] == "active"
        assert result["is_weighing"] is False
        assert result["image_url"] == "https://img.example.com/dcyt.jpg"
        assert result["source_system"] == "pinzhi"

    def test_dish_with_specs_and_practices(self):
        """品智菜品含规格(SKU)和做法时正确映射"""
        from src.dish_sync import PinzhiDishSync

        raw = {
            "dishId": "D200",
            "dishName": "水煮鱼",
            "dishPrice": 8800,
            "status": 1,
            "specList": [
                {"specId": "SP1", "specName": "大份", "specPrice": 12800},
                {"specId": "SP2", "specName": "小份", "specPrice": 6800},
            ],
            "practiceList": [
                {"practiceId": "PR1", "practiceName": "微辣", "extraPrice": 0},
                {"practiceId": "PR2", "practiceName": "加辣", "extraPrice": 200},
            ],
        }

        result = PinzhiDishSync.map_to_tunxiang_dish(raw)

        assert len(result["specs"]) == 2
        assert result["specs"][0]["spec_name"] == "大份"
        assert result["specs"][0]["price_fen"] == 12800
        assert len(result["practices"]) == 2
        assert result["practices"][1]["practice_name"] == "加辣"
        assert result["practices"][1]["extra_price_fen"] == 200

    def test_dish_inactive_status(self):
        """品智停用菜品(status=0)映射为 inactive"""
        from src.dish_sync import PinzhiDishSync

        raw = {"dishId": "D300", "dishName": "已下架菜", "dishPrice": 1000, "status": 0}

        result = PinzhiDishSync.map_to_tunxiang_dish(raw)
        assert result["status"] == "inactive"

    def test_dish_missing_optional_fields_defaults(self):
        """品智菜品缺少可选字段时使用默认值"""
        from src.dish_sync import PinzhiDishSync

        raw = {"dishId": "D400", "dishName": "简单菜"}

        result = PinzhiDishSync.map_to_tunxiang_dish(raw)
        assert result["price_fen"] == 0
        assert result["cost_fen"] == 0
        assert result["unit"] == "份"
        assert result["specs"] == []
        assert result["practices"] == []
        assert result["image_url"] is None


# ---------------------------------------------------------------------------
# P1-1: to_order 高级字段测试（做法/赠菜/套餐/服务费）
# ---------------------------------------------------------------------------

class TestToOrderAdvancedFields:
    """to_order 高级字段映射：做法/口味/赠菜/套餐/服务费"""

    def test_dish_with_practice_and_taste(self, adapter):
        """菜品含做法和口味时正确拼接 practice_names"""
        raw = {
            "billId": "ADV001", "billNo": "ADV001", "billStatus": 1,
            "orderSource": 1, "dishPriceTotal": 8800,
            "specialOfferPrice": 0, "realPrice": 8800, "teaPrice": 0,
            "dishList": [{
                "dishId": "D010", "dishName": "红烧肉", "dishNum": 1, "dishPrice": 8800,
                "practice": [{"name": "微辣"}],
                "taste": [{"tasteName": "少盐"}],
            }],
        }
        order = adapter.to_order(raw, "S1", "B1")
        assert order.items[0].practice_names == "微辣,少盐"

    def test_dish_gift_flag(self, adapter):
        """赠菜标记正确映射"""
        raw = {
            "billId": "GIFT001", "billNo": "GIFT001", "billStatus": 1,
            "orderSource": 1, "dishPriceTotal": 0,
            "specialOfferPrice": 0, "realPrice": 0, "teaPrice": 0,
            "dishList": [{
                "dishId": "D011", "dishName": "赠菜", "dishNum": 1, "dishPrice": 0,
                "isGift": True, "giftReason": "VIP客户赠送",
            }],
        }
        order = adapter.to_order(raw, "S1", "B1")
        assert order.items[0].is_gift is True
        assert order.items[0].gift_reason == "VIP客户赠送"

    def test_dish_combo_id(self, adapter):
        """套餐ID正确映射"""
        raw = {
            "billId": "COMBO001", "billNo": "COMBO001", "billStatus": 1,
            "orderSource": 1, "dishPriceTotal": 19800,
            "specialOfferPrice": 0, "realPrice": 19800, "teaPrice": 0,
            "dishList": [{
                "dishId": "D012", "dishName": "套餐主菜", "dishNum": 1, "dishPrice": 19800,
                "comboId": "COMBO_A",
            }],
        }
        order = adapter.to_order(raw, "S1", "B1")
        assert order.items[0].combo_id == "COMBO_A"

    def test_service_charge_fen_field(self, adapter):
        """service_charge_fen 字段从 teaPrice 映射"""
        raw = {
            "billId": "SVC001", "billNo": "SVC001", "billStatus": 1,
            "orderSource": 1, "dishPriceTotal": 10000,
            "specialOfferPrice": 0, "realPrice": 10500, "teaPrice": 500,
        }
        order = adapter.to_order(raw, "S1", "B1")
        assert order.service_charge_fen == 500
        assert order.service_charge == Decimal("5.00")

    def test_cashier_id_mapped(self, adapter):
        """收银员ID正确映射"""
        raw = {
            "billId": "CASH001", "billNo": "CASH001", "billStatus": 1,
            "orderSource": 1, "dishPriceTotal": 5000,
            "specialOfferPrice": 0, "realPrice": 5000, "teaPrice": 0,
            "cashiers": "CASHIER_007",
        }
        order = adapter.to_order(raw, "S1", "B1")
        assert order.cashier_id == "CASHIER_007"

    def test_order_source_preserved(self, adapter):
        """品智 orderSource 原始值保留为字符串"""
        raw = {
            "billId": "SRC001", "billNo": "SRC001", "billStatus": 1,
            "orderSource": 3, "dishPriceTotal": 5000,
            "specialOfferPrice": 0, "realPrice": 5000, "teaPrice": 0,
        }
        order = adapter.to_order(raw, "S1", "B1")
        assert order.order_source == "3"


# ---------------------------------------------------------------------------
# P1-1: 网络异常细分测试
# ---------------------------------------------------------------------------

class TestNetworkErrorDetails:
    """网络错误细分测试：区分超时、连接失败、解码失败"""

    @pytest.mark.asyncio
    async def test_connect_timeout_propagates(self, adapter):
        """连接超时异常透传"""
        adapter.client.get = AsyncMock(
            side_effect=httpx.ConnectTimeout("连接超时")
        )
        with pytest.raises(httpx.ConnectTimeout):
            await adapter.get_store_info()

    @pytest.mark.asyncio
    async def test_connect_error_propagates(self, adapter):
        """连接失败（如DNS解析失败）异常透传"""
        adapter.client.get = AsyncMock(
            side_effect=httpx.ConnectError("DNS解析失败")
        )
        with pytest.raises(httpx.ConnectError):
            await adapter.get_store_info()

    @pytest.mark.asyncio
    async def test_decoding_error_propagates(self, adapter):
        """响应解码失败异常透传"""
        adapter.client.post = AsyncMock(
            side_effect=httpx.DecodingError("UTF-8 decode failed")
        )
        with pytest.raises(httpx.DecodingError):
            await adapter.query_orders(business_date="2024-01-01")

    @pytest.mark.asyncio
    async def test_graceful_degradation_on_tables_timeout(self, adapter):
        """桌台查询超时时降级返回空列表（非核心接口有fallback）"""
        adapter.client.get = AsyncMock(
            side_effect=httpx.ConnectTimeout("timeout")
        )
        result = await adapter.get_tables()
        assert result == []

    @pytest.mark.asyncio
    async def test_graceful_degradation_on_employees_timeout(self, adapter):
        """员工查询超时时降级返回空列表"""
        adapter.client.get = AsyncMock(
            side_effect=httpx.ConnectTimeout("timeout")
        )
        result = await adapter.get_employees()
        assert result == []


# ---------------------------------------------------------------------------
# P1-1: 多门店并发拉取隔离测试
# ---------------------------------------------------------------------------

class TestMultiStoreConcurrentIsolation:
    """验证多门店并发拉取时数据不混淆"""

    @pytest.mark.asyncio
    async def test_concurrent_fetch_different_stores(self, adapter_store_a, adapter_store_b):
        """两个门店同时拉取订单，数据互不干扰"""
        import asyncio

        response_a = {"success": 0, "res": [{"billId": "A_ORDER_001", "store": "A"}]}
        response_b = {"success": 0, "res": [{"billId": "B_ORDER_001", "store": "B"}]}

        adapter_store_a.client.post = AsyncMock(return_value=_mock_response(response_a))
        adapter_store_b.client.post = AsyncMock(return_value=_mock_response(response_b))

        result_a, result_b = await asyncio.gather(
            adapter_store_a.query_orders(ognid="STORE_A", business_date="2024-01-01"),
            adapter_store_b.query_orders(ognid="STORE_B", business_date="2024-01-01"),
        )

        assert result_a[0]["billId"] == "A_ORDER_001"
        assert result_b[0]["billId"] == "B_ORDER_001"
        assert result_a[0]["store"] == "A"
        assert result_b[0]["store"] == "B"

    @pytest.mark.asyncio
    async def test_to_order_store_id_isolation(self, adapter):
        """to_order 映射时 store_id/brand_id 按参数注入，不混用"""
        raw = {
            "billId": "ISO001", "billNo": "ISO001", "billStatus": 1,
            "orderSource": 1, "dishPriceTotal": 1000,
            "specialOfferPrice": 0, "realPrice": 1000, "teaPrice": 0,
        }

        order_a = adapter.to_order(raw, store_id="STORE_A", brand_id="BRAND_X")
        order_b = adapter.to_order(raw, store_id="STORE_B", brand_id="BRAND_Y")

        assert order_a.store_id == "STORE_A"
        assert order_a.brand_id == "BRAND_X"
        assert order_b.store_id == "STORE_B"
        assert order_b.brand_id == "BRAND_Y"


# ---------------------------------------------------------------------------
# P1-1: DishSync 集成测试
# ---------------------------------------------------------------------------

class TestDishSyncIntegration:
    """DishSync 拉取+映射完整流程测试"""

    @pytest.mark.asyncio
    async def test_sync_dishes_full_flow(self, adapter):
        """完整同步流程：拉取 + 映射 + 统计"""
        from src.dish_sync import PinzhiDishSync

        mock_response_data = {
            "success": 0,
            "data": [
                {"dishId": "D1", "dishName": "菜A", "dishPrice": 5000, "status": 1},
                {"dishId": "D2", "dishName": "菜B", "dishPrice": 8800, "status": 1},
                {"dishId": "D3", "dishName": "菜C", "dishPrice": 3200, "status": 0},
            ],
        }
        adapter.client.post = AsyncMock(return_value=_mock_response(mock_response_data))
        adapter.client.get = AsyncMock(return_value=_mock_response(mock_response_data))

        syncer = PinzhiDishSync(adapter)
        result = await syncer.sync_dishes(brand_id="BRAND_TEST")

        assert result["total"] == 3
        assert result["success"] == 3
        assert result["failed"] == 0
        assert len(result["dishes"]) == 3
        assert result["dishes"][0]["dish_name"] == "菜A"
        assert result["dishes"][2]["status"] == "inactive"

    @pytest.mark.asyncio
    async def test_sync_dishes_empty_response(self, adapter):
        """品智返回空菜品列表时同步结果为零"""
        from src.dish_sync import PinzhiDishSync

        mock_response_data = {"success": 0, "data": []}
        adapter.client.post = AsyncMock(return_value=_mock_response(mock_response_data))
        adapter.client.get = AsyncMock(return_value=_mock_response(mock_response_data))

        syncer = PinzhiDishSync(adapter)
        result = await syncer.sync_dishes(brand_id="BRAND_TEST")

        assert result["total"] == 0
        assert result["dishes"] == []
