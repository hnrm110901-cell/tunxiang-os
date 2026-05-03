"""易订适配器健康检查和幂等性专项测试"""

import pytest

from shared.adapters.yiding.src.adapter import YiDingAdapter
from shared.adapters.yiding.src.types import YiDingConfig


@pytest.fixture
def config() -> YiDingConfig:
    return {
        "base_url": "https://open.zhidianfan.com/yidingopen/",
        "appid": "test_app",
        "secret": "test_secret",
        "hotel_id": "30",
    }


@pytest.fixture
def adapter(config: YiDingConfig) -> YiDingAdapter:
    return YiDingAdapter(config)


class TestYiDingHealth:
    """健康检查相关测试"""

    async def test_health_check_success(self, adapter, mocker):
        """健康检查正常返回 True"""
        mocker.patch.object(adapter.client, "ping", return_value=True)
        assert await adapter.health_check() is True

    async def test_health_check_failure(self, adapter, mocker):
        """健康检查异常时返回 False"""
        mocker.patch.object(adapter.client, "ping", side_effect=ConnectionError("timeout"))
        assert await adapter.health_check() is False

    async def test_health_check_returns_false_on_exception(self, adapter, mocker):
        """健康检查捕获任意异常均返回 False"""
        mocker.patch.object(adapter.client, "ping", side_effect=RuntimeError("unexpected"))
        assert await adapter.health_check() is False


class TestYiDingIdempotency:
    """幂等性键生成与去重测试"""

    def test_idempotency_key_reproducible(self, adapter):
        """相同参数生成相同的幂等键"""
        key1 = adapter.idempotency_key("sync_tables", {"tables": ["A", "B"]})
        key2 = adapter.idempotency_key("sync_tables", {"tables": ["A", "B"]})
        assert key1 == key2

    def test_idempotency_key_different_payload(self, adapter):
        """不同参数生成不同的幂等键"""
        key1 = adapter.idempotency_key("sync_tables", {"tables": ["A"]})
        key2 = adapter.idempotency_key("sync_tables", {"tables": ["B"]})
        assert key1 != key2

    def test_idempotency_key_different_operation(self, adapter):
        """不同操作名生成不同的幂等键"""
        key1 = adapter.idempotency_key("sync_tables", {"tables": ["A"]})
        key2 = adapter.idempotency_key("sync_dishes", {"tables": ["A"]})
        assert key1 != key2

    def test_is_duplicate_returns_true_after_mark(self, adapter):
        """标记后相同请求应判为重复"""
        key = adapter.idempotency_key("sync_tables", {"tables": ["A"]})
        assert adapter.is_duplicate(key) is False
        adapter.mark_idempotent(key)
        assert adapter.is_duplicate(key) is True

    def test_is_duplicate_unmarked_key(self, adapter):
        """未标记的请求不应判为重复"""
        key = adapter.idempotency_key("sync_tables", {"tables": ["X"]})
        assert adapter.is_duplicate(key) is False


class TestYiDingSystemInfo:
    """系统信息相关测试"""

    def test_get_system_name(self, adapter):
        """系统名应返回 yiding"""
        assert adapter.get_system_name() == "yiding"

    async def test_close_cleans_up(self, adapter, mocker):
        """close 应调用 client.close"""
        mock_close = mocker.patch.object(adapter.client, "close")
        await adapter.close()
        mock_close.assert_awaited_once()
