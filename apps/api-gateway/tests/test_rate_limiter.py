"""
R1: 公开接口限流中间件 — 单元测试

测试内容：
- IP 限流（30次/分钟）
- SMS 限流（5条/小时）
- 过期清理逻辑
- 429 异常抛出
"""
import os
for _k, _v in {
    "APP_ENV": "test",
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
    "REDIS_URL": "redis://localhost:6379/0",
    "CELERY_BROKER_URL": "redis://localhost:6379/0",
    "CELERY_RESULT_BACKEND": "redis://localhost:6379/0",
    "SECRET_KEY": "test-secret-key",
    "JWT_SECRET": "test-jwt-secret",
}.items():
    os.environ.setdefault(_k, _v)

import pytest
import time as time_module
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi import HTTPException

from src.middleware.public_rate_limiter import (
    check_ip_rate_limit,
    check_sms_rate_limit,
    _cleanup,
    _ip_requests,
    _sms_requests,
    IP_LIMIT,
    IP_WINDOW,
    SMS_LIMIT,
    SMS_WINDOW,
)


@pytest.fixture(autouse=True)
def clear_stores():
    """每个测试前清空限流存储"""
    _ip_requests.clear()
    _sms_requests.clear()
    yield
    _ip_requests.clear()
    _sms_requests.clear()


class TestCleanup:

    def test_removes_expired_entries(self):
        now = time_module.time()
        store = {"key1": [now - 200, now - 100, now - 10]}
        _cleanup(store, 60)
        # Only entries within 60s should remain
        assert len(store["key1"]) == 1

    def test_removes_empty_keys(self):
        now = time_module.time()
        store = {"key1": [now - 200]}
        _cleanup(store, 60)
        assert "key1" not in store

    def test_keeps_valid_entries(self):
        now = time_module.time()
        store = {"key1": [now - 5, now - 10]}
        _cleanup(store, 60)
        assert len(store["key1"]) == 2


class TestIPRateLimit:

    @pytest.mark.asyncio
    async def test_allows_first_request(self):
        request = MagicMock()
        request.client.host = "192.168.1.1"
        await check_ip_rate_limit(request)
        assert len(_ip_requests["192.168.1.1"]) == 1

    @pytest.mark.asyncio
    async def test_allows_under_limit(self):
        request = MagicMock()
        request.client.host = "192.168.1.2"
        for _ in range(IP_LIMIT - 1):
            await check_ip_rate_limit(request)
        assert len(_ip_requests["192.168.1.2"]) == IP_LIMIT - 1

    @pytest.mark.asyncio
    async def test_blocks_at_limit(self):
        request = MagicMock()
        request.client.host = "192.168.1.3"
        # Fill to limit
        now = time_module.time()
        _ip_requests["192.168.1.3"] = [now] * IP_LIMIT

        with pytest.raises(HTTPException) as exc_info:
            await check_ip_rate_limit(request)
        assert exc_info.value.status_code == 429
        assert "请求过于频繁" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_unknown_client(self):
        request = MagicMock()
        request.client = None
        # Should use "unknown" as IP
        await check_ip_rate_limit(request)
        assert "unknown" in _ip_requests

    @pytest.mark.asyncio
    async def test_different_ips_independent(self):
        req1 = MagicMock()
        req1.client.host = "10.0.0.1"
        req2 = MagicMock()
        req2.client.host = "10.0.0.2"

        await check_ip_rate_limit(req1)
        await check_ip_rate_limit(req2)

        assert len(_ip_requests["10.0.0.1"]) == 1
        assert len(_ip_requests["10.0.0.2"]) == 1


class TestSMSRateLimit:

    @pytest.mark.asyncio
    async def test_allows_first_sms(self):
        await check_sms_rate_limit("13800138000")
        assert len(_sms_requests["13800138000"]) == 1

    @pytest.mark.asyncio
    async def test_allows_under_limit(self):
        for _ in range(SMS_LIMIT - 1):
            await check_sms_rate_limit("13900139000")
        assert len(_sms_requests["13900139000"]) == SMS_LIMIT - 1

    @pytest.mark.asyncio
    async def test_blocks_at_limit(self):
        now = time_module.time()
        _sms_requests["13700137000"] = [now] * SMS_LIMIT

        with pytest.raises(HTTPException) as exc_info:
            await check_sms_rate_limit("13700137000")
        assert exc_info.value.status_code == 429
        assert "短信发送过于频繁" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_different_phones_independent(self):
        await check_sms_rate_limit("13100131000")
        await check_sms_rate_limit("13200132000")
        assert len(_sms_requests["13100131000"]) == 1
        assert len(_sms_requests["13200132000"]) == 1

    @pytest.mark.asyncio
    async def test_expired_entries_dont_count(self):
        # All entries older than window
        old_time = time_module.time() - SMS_WINDOW - 10
        _sms_requests["13600136000"] = [old_time] * SMS_LIMIT

        # Should pass because old entries are expired
        await check_sms_rate_limit("13600136000")
        # Old entries cleaned + 1 new
        assert len(_sms_requests["13600136000"]) == 1


class TestConstants:

    def test_ip_limit(self):
        assert IP_LIMIT == 30

    def test_ip_window(self):
        assert IP_WINDOW == 60

    def test_sms_limit(self):
        assert SMS_LIMIT == 5

    def test_sms_window(self):
        assert SMS_WINDOW == 3600
