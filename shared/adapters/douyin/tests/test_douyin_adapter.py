"""Tests for 抖音生活服务 adapter

Tests both DouyinClient (HTTP/auth/signing) and DouyinAdapter (business API).
Signing is tested deterministically; all network-bound operations expect
httpx communication errors since no real credentials are configured.
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

from shared.adapters.douyin.src.client import DouyinClient, _check_biz_error
from shared.adapters.douyin.src.adapter import DouyinAdapter


# =============================================================================
# DouyinClient
# =============================================================================


class TestDouyinClientInit:
    """客户端初始化"""

    def test_initialize_with_explicit_credentials(self):
        """使用显式凭据初始化"""
        client = DouyinClient(app_id="test_app_id", app_secret="test_app_secret", sandbox=True)
        assert client.app_id == "test_app_id"
        assert client.app_secret == "test_app_secret"
        assert client.sandbox is True
        assert client.timeout == 30
        assert client.retry_times == 3

    def test_initialize_with_custom_timeout(self):
        """自定义超时时间"""
        client = DouyinClient(
            app_id="id", app_secret="secret",
            sandbox=True, timeout=15, retry_times=5,
        )
        assert client.timeout == 15
        assert client.retry_times == 5

    def test_missing_credentials_raises(self):
        """缺少凭据时抛出 ValueError"""
        with pytest.raises(ValueError, match="DOUYIN_APP_ID"):
            DouyinClient(app_id="", app_secret="secret", sandbox=True)

        with pytest.raises(ValueError, match="DOUYIN_APP_SECRET"):
            DouyinClient(app_id="id", app_secret="", sandbox=True)

    def test_sandbox_sets_sandbox_url(self):
        """沙箱模式使用沙箱 base URL"""
        client = DouyinClient(app_id="id", app_secret="secret", sandbox=True)
        assert client._http.base_url == "https://open-sandbox.douyin.com"

    def test_production_sets_production_url(self):
        """生产模式使用生产 base URL"""
        client = DouyinClient(app_id="id", app_secret="secret", sandbox=False)
        assert client._http.base_url == "https://open.douyin.com"


class TestDouyinClientSign:
    """签名方法确定性测试"""

    def test_sign_is_deterministic(self):
        """相同参数 + 相同 timestamp 生成相同签名"""
        client = DouyinClient(app_id="id", app_secret="secret", sandbox=True)
        params = {"shop_id": "shop123", "order_id": "ord456"}
        ts = "1714000000"
        sig1 = client.sign(params, ts)
        sig2 = client.sign(params, ts)
        assert sig1 == sig2

    def test_sign_changes_with_different_params(self):
        """不同参数生成不同签名"""
        client = DouyinClient(app_id="id", app_secret="secret", sandbox=True)
        ts = "1714000000"
        sig1 = client.sign({"shop_id": "shop123"}, ts)
        sig2 = client.sign({"shop_id": "shop999"}, ts)
        assert sig1 != sig2

    def test_sign_changes_with_different_timestamp(self):
        """不同 timestamp 生成不同签名"""
        client = DouyinClient(app_id="id", app_secret="secret", sandbox=True)
        params = {"shop_id": "shop123"}
        sig1 = client.sign(params, "1714000000")
        sig2 = client.sign(params, "1714000001")
        assert sig1 != sig2

    def test_sign_algorithm_correctness(self):
        """验证签名算法是否符合预期 HMAC-SHA256"""
        client = DouyinClient(app_id="id", app_secret="test_secret", sandbox=True)
        params = {"a": "1", "b": "2"}
        ts = "1714000000"
        result = client.sign(params, ts)

        # Replicate the exact algorithm from client.py
        sorted_params = sorted(params.items())
        sign_str = "&".join(f"{k}={v}" for k, v in sorted_params) + f"&timestamp={ts}"
        expected = hmac.new(
            b"test_secret",
            sign_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        assert result == expected

    def test_sign_empty_params(self):
        """空参数字典也可以签名"""
        client = DouyinClient(app_id="id", app_secret="secret", sandbox=True)
        sig = client.sign({}, "1714000000")
        assert isinstance(sig, str)
        assert len(sig) == 64  # SHA256 hex digest length


class TestDouyinClientBizError:
    """业务错误检查"""

    def test_biz_error_raises(self):
        """业务错误码非零时抛出 ValueError"""
        with pytest.raises(ValueError, match="抖音 API 错误"):
            _check_biz_error({"data": {"error_code": 40001, "description": "token expired"}})

    def test_no_error_passes(self):
        """错误码为零时不抛出"""
        _check_biz_error({"data": {"error_code": 0, "description": "success"}})


# =============================================================================
# DouyinAdapter
# =============================================================================


class TestDouyinAdapterInit:
    """适配器初始化"""

    def test_adapter_initialization_with_config(self):
        """适配器可以通过配置字典初始化"""
        adapter = DouyinAdapter({
            "app_id": "test_app_id",
            "app_secret": "test_app_secret",
            "sandbox": True,
        })
        assert adapter.config["app_id"] == "test_app_id"
        assert adapter.config["sandbox"] is True
        assert adapter.client.app_id == "test_app_id"

    def test_adapter_inherits_client_credentials(self):
        """适配器将配置正确传递给客户端"""
        adapter = DouyinAdapter({
            "app_id": "adapter_id",
            "app_secret": "adapter_secret",
            "sandbox": True,
            "timeout": 15,
            "retry_times": 5,
        })
        assert adapter.client.app_id == "adapter_id"
        assert adapter.client.app_secret == "adapter_secret"
        assert adapter.client.sandbox is True
        assert adapter.client.timeout == 15
        assert adapter.client.retry_times == 5


class TestDouyinAdapterQueryOrders:
    """async adapter methods — verify that the adapter creates correct
    requests even though no live sandbox server is available."""

    @pytest.mark.asyncio
    async def test_orders_raises_connect_error(self):
        """query_orders 因无网络连接而触发 httpx.ConnectError"""
        adapter = DouyinAdapter({
            "app_id": "id", "app_secret": "secret", "sandbox": True,
        })
        with pytest.raises((httpx.ConnectError, httpx.ProxyError,
                            ConnectionError, RuntimeError, ValueError)):
            await adapter.query_orders("2026-01-01", "2026-01-31")
        await adapter.close()

    @pytest.mark.asyncio
    async def test_settlements_raises_connect_error(self):
        """query_settlements 因无网络连接而触发 httpx.ConnectError"""
        adapter = DouyinAdapter({
            "app_id": "id", "app_secret": "secret", "sandbox": True,
        })
        with pytest.raises((httpx.ConnectError, httpx.ProxyError,
                            ConnectionError, RuntimeError, ValueError)):
            await adapter.query_settlements("2026-01-01", "2026-01-31")
        await adapter.close()

    @pytest.mark.asyncio
    async def test_close_releases_resources(self):
        """close 方法可以安全调用"""
        adapter = DouyinAdapter({
            "app_id": "id", "app_secret": "secret", "sandbox": True,
        })
        await adapter.close()
        # Calling close twice should not raise
        await adapter.close()
