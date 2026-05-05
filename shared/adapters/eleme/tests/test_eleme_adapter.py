"""Tests for 饿了么 adapter

Tests both ElemeClient (HTTP/auth/signing) and ElemeAdapter (business API).
Signing is tested deterministically; network-bound operations expect httpx
communication errors since no real credentials are configured.
"""

import os

# httpx reads proxy config from environment on client creation.  The outer
# shell has ALL_PROXY=socks5h://... which httpx 0.26 cannot parse, so
# clear all proxy variables before importing httpx.
for _key in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy",
             "HTTPS_PROXY", "https_proxy"):
    os.environ.pop(_key, None)

import hashlib
import hmac

import httpx
import pytest

from shared.adapters.eleme.src.client import ElemeClient, _check_biz_error
from shared.adapters.eleme.src.adapter import ElemeAdapter


# =============================================================================
# ElemeClient
# =============================================================================


class TestElemeClientInit:
    """客户端初始化"""

    def test_initialize_with_explicit_credentials(self):
        """使用显式凭据初始化"""
        client = ElemeClient(app_key="test_key", app_secret="test_secret", sandbox=True)
        assert client.app_key == "test_key"
        assert client.app_secret == "test_secret"
        assert client.sandbox is True
        assert client.store_id == ""
        assert client.timeout == 30
        assert client.retry_times == 3

    def test_initialize_with_store_id(self):
        """初始化时指定 store_id"""
        client = ElemeClient(
            app_key="key", app_secret="secret",
            store_id="store_123", sandbox=True,
        )
        assert client.store_id == "store_123"

    def test_missing_credentials_raises(self):
        """缺少凭据时抛出 ValueError"""
        with pytest.raises(ValueError, match="ELEME_APP_KEY"):
            ElemeClient(app_key="", app_secret="secret", sandbox=True)

        with pytest.raises(ValueError, match="ELEME_APP_SECRET"):
            ElemeClient(app_key="key", app_secret="", sandbox=True)

    def test_sandbox_sets_sandbox_url(self):
        """沙箱模式 base URL 包含 sandbox"""
        client = ElemeClient(app_key="key", app_secret="secret", sandbox=True)
        assert "sandbox" in client.base_url

    def test_production_sets_production_url(self):
        """生产模式 base URL 不包含 sandbox"""
        client = ElemeClient(app_key="key", app_secret="secret", sandbox=False)
        assert "sandbox" not in client.base_url


class TestElemeClientSign:
    """签名方法确定性测试"""

    def test_sign_is_deterministic(self):
        """相同参数生成相同签名（大写 hex）"""
        client = ElemeClient(app_key="key", app_secret="secret", sandbox=True)
        params = {"shop_id": "shop123", "order_id": "ord456"}
        sig1 = client.sign(params)
        sig2 = client.sign(params)
        assert sig1 == sig2

    def test_sign_changes_with_different_params(self):
        """不同参数生成不同签名"""
        client = ElemeClient(app_key="key", app_secret="secret", sandbox=True)
        sig1 = client.sign({"shop_id": "shop123"})
        sig2 = client.sign({"shop_id": "shop999"})
        assert sig1 != sig2

    def test_sign_returns_uppercase(self):
        """饿了么签名返回大写 hex"""
        client = ElemeClient(app_key="key", app_secret="secret", sandbox=True)
        sig = client.sign({"a": "1"})
        assert sig == sig.upper()

    def test_sign_algorithm_correctness(self):
        """验证签名算法是否符合预期的拼接规则"""
        client = ElemeClient(app_key="key", app_secret="test_secret", sandbox=True)
        params = {"a": "1", "b": "2"}
        result = client.sign(params)

        # Replicate the exact algorithm from client.py:
        #   sign_str = app_secret + k1v1k2v2... + app_secret
        sorted_params = sorted(params.items())
        sign_str = "test_secret"
        for k, v in sorted_params:
            sign_str += f"{k}{v}"
        sign_str += "test_secret"

        expected = hmac.new(
            b"test_secret",
            sign_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest().upper()

        assert result == expected

    def test_sign_include_timestamp(self):
        """sign 包含 timestamp 时也能正确计算"""
        client = ElemeClient(app_key="key", app_secret="secret", sandbox=True)
        params = {"app_key": "key", "access_token": "tok123", "timestamp": "1714000000"}
        sig = client.sign(params)
        assert isinstance(sig, str)
        assert len(sig) == 64  # SHA256 hex digest


class TestElemeClientBizError:
    """业务错误检查"""

    def test_biz_error_raises_with_code_string(self):
        """错误码 '400' 字符串时抛出 ValueError"""
        with pytest.raises(ValueError, match="饿了么 API 错误"):
            _check_biz_error({"code": "400", "message": "invalid params"})

    def test_biz_error_raises_with_code_int(self):
        """错误码 400 整数时抛出 ValueError"""
        with pytest.raises(ValueError, match="饿了么 API 错误"):
            _check_biz_error({"code": 400, "message": "invalid params"})

    def test_no_error_passes_with_code_200(self):
        """状态码 200 时不抛出"""
        _check_biz_error({"code": "200", "message": "ok"})

    def test_no_error_passes_with_code_ok(self):
        """状态码 'ok' 时不抛出"""
        _check_biz_error({"code": "ok", "message": "success"})

    def test_no_error_passes_without_code(self):
        """没有 code 字段时不抛出"""
        _check_biz_error({"result": "success"})


# =============================================================================
# ElemeAdapter
# =============================================================================


class TestElemeAdapterInit:
    """适配器初始化"""

    def test_adapter_initialization_with_config(self):
        """适配器可以通过配置字典初始化"""
        adapter = ElemeAdapter({
            "app_key": "test_key",
            "app_secret": "test_secret",
            "sandbox": True,
        })
        assert adapter.config["app_key"] == "test_key"
        assert adapter.config["sandbox"] is True
        assert adapter.client.app_key == "test_key"

    def test_adapter_inherits_client_credentials(self):
        """适配器将配置正确传递给客户端"""
        adapter = ElemeAdapter({
            "app_key": "adapter_key",
            "app_secret": "adapter_secret",
            "store_id": "store_999",
            "sandbox": True,
            "timeout": 10,
            "retry_times": 2,
        })
        assert adapter.client.app_key == "adapter_key"
        assert adapter.client.app_secret == "adapter_secret"
        assert adapter.client.store_id == "store_999"
        assert adapter.client.sandbox is True
        assert adapter.client.timeout == 10
        assert adapter.client.retry_times == 2


class TestElemeAdapterQueryOrders:
    """async adapter methods — verify request creation even offline."""

    @pytest.mark.asyncio
    async def test_orders_raises_connect_error(self):
        """query_orders 因无网络连接而触发 httpx.ConnectError"""
        adapter = ElemeAdapter({
            "app_key": "key", "app_secret": "secret", "sandbox": True,
        })
        with pytest.raises((httpx.ConnectError, httpx.ProxyError,
                            ConnectionError, RuntimeError, ValueError)):
            await adapter.query_orders()
        await adapter.close()

    @pytest.mark.asyncio
    async def test_close_releases_resources(self):
        """close 方法可以安全调用"""
        adapter = ElemeAdapter({
            "app_key": "key", "app_secret": "secret", "sandbox": True,
        })
        await adapter.close()
        # Calling close twice should not raise
        await adapter.close()


class TestElemeAdapterToOrder:
    """to_order() 标准化数据映射

    NOTE: to_order() does a runtime sys.path hack to import
    ``schemas.restaurant_standard_schema`` from ``apps/api-gateway/src``.
    That directory no longer exists in this checkout, so these tests are
    marked xfail.  They become actionable once the schema module
    is restored or provided as an installable package.
    """

    _raw_minimal = {
        "order_id": "el123",
        "status": 4,
        "total_price": 5000,
        "food_list": [
            {"food_id": "f1", "food_name": "红烧肉", "quantity": 2, "price": 2000},
        ],
    }

    _raw_cancelled = {
        "order_id": "el789",
        "status": 5,
        "total_price": 0,
        "food_list": [],
    }

    _raw_items_alias = {
        "order_id": "el999",
        "status": 1,
        "total_price": 1500,
        "items": [
            {"sku_id": "sk1", "name": "蛋炒饭", "count": 1, "price": 1500},
        ],
    }

    @pytest.mark.xfail(
        strict=False,
        reason="依赖 apps/api-gateway/src/schemas/restaurant_standard_schema.py，该模块当前不可用",
    )
    def test_to_order_minimal_fields(self):
        """最简字段也可映射为 OrderSchema"""
        adapter = ElemeAdapter({
            "app_key": "key", "app_secret": "secret", "sandbox": True,
        })
        result = adapter.to_order(self._raw_minimal, store_id="store_1", brand_id="brand_1")
        assert result.order_id == "el123"
        assert result.store_id == "store_1"
        assert result.brand_id == "brand_1"
        assert len(result.items) == 1
        assert result.items[0].dish_name == "红烧肉"
        assert result.items[0].quantity == 2
        # Price is in 分 in raw, converted to 元
        assert float(result.items[0].unit_price) == 20.0
        assert float(result.total) == 50.0

    @pytest.mark.xfail(
        strict=False,
        reason="依赖 apps/api-gateway/src/schemas/restaurant_standard_schema.py",
    )
    def test_to_order_completed_status_mapping(self):
        """已完成订单 (status=4) 映射为 COMPLETED"""
        adapter = ElemeAdapter({
            "app_key": "key", "app_secret": "secret", "sandbox": True,
        })
        result = adapter.to_order(self._raw_minimal, store_id="s1", brand_id="b1")
        assert result.order_status.value == "completed"

    @pytest.mark.xfail(
        strict=False,
        reason="依赖 apps/api-gateway/src/schemas/restaurant_standard_schema.py",
    )
    def test_to_order_cancelled_status_mapping(self):
        """取消订单 (status=5) 映射为 CANCELLED"""
        adapter = ElemeAdapter({
            "app_key": "key", "app_secret": "secret", "sandbox": True,
        })
        result = adapter.to_order(self._raw_cancelled, store_id="s1", brand_id="b1")
        assert result.order_status.value == "cancelled"

    @pytest.mark.xfail(
        strict=False,
        reason="依赖 apps/api-gateway/src/schemas/restaurant_standard_schema.py",
    )
    def test_to_order_with_items_alias(self):
        """支持 items 字段作为 food_list 的别名"""
        adapter = ElemeAdapter({
            "app_key": "key", "app_secret": "secret", "sandbox": True,
        })
        result = adapter.to_order(self._raw_items_alias, store_id="s1", brand_id="b1")
        assert len(result.items) == 1
        assert result.items[0].dish_id == "sk1"
        assert result.items[0].dish_name == "蛋炒饭"
        assert result.items[0].quantity == 1
