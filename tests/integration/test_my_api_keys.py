"""API Key 管理 + Webhook 投递集成测试

验证密钥生成/哈希/验证、Webhook 签名/投递/重试逻辑。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _load_module(name: str, path: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ═══════════════════════════════════════════════════════════════════════════
# API Key Generator
# ═══════════════════════════════════════════════════════════════════════════


class TestApiKeyGenerator:
    """API 密钥生成器"""

    @pytest.fixture
    def gen(self):
        return _load_module(
            "key_generator",
            "shared/apikeys/src/key_generator.py",
        )

    def test_generate_api_key_format(self, gen):
        """密钥格式: tx_ + 48 base62 chars = 51 chars"""
        full_key, prefix, key_hash = gen.generate_api_key()
        assert full_key.startswith("tx_")
        assert len(full_key) == 51
        assert len(prefix) == 10
        assert len(key_hash) == 64  # SHA-256 hex

    def test_validate_key_format_valid(self, gen):
        """有效密钥通过校验"""
        full_key, _, _ = gen.generate_api_key()
        assert gen.validate_key_format(full_key) is True

    def test_validate_key_format_invalid_prefix(self, gen):
        """无效前缀"""
        assert gen.validate_key_format("invalid_key_123") is False

    def test_validate_key_format_short(self, gen):
        """过短密钥"""
        assert gen.validate_key_format("tx_short") is False

    def test_hash_consistency(self, gen):
        """同一密钥两次哈希结果一致"""
        full_key, _, hash1 = gen.generate_api_key()
        hash2 = gen.hash_api_key(full_key)
        assert hash1 == hash2

    def test_different_keys_different_hashes(self, gen):
        """不同密钥哈希不同"""
        _, _, h1 = gen.generate_api_key()
        _, _, h2 = gen.generate_api_key()
        assert h1 != h2


# ═══════════════════════════════════════════════════════════════════════════
# API Key CRUD Service
# ═══════════════════════════════════════════════════════════════════════════


class TestApiKeyService:
    """API 密钥 CRUD 服务"""

    MOCK_TENANT = "a0000000-0000-0000-0000-000000000001"

    @pytest.fixture
    def key_service(self):
        # 先加载 key_generator（.key_generator 相对导入依赖）
        _load_module(
            "shared.apikeys.src.key_generator",
            "shared/apikeys/src/key_generator.py",
        )
        mod = _load_module(
            "shared.apikeys.src.key_service",
            "shared/apikeys/src/key_service.py",
        )
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_result.fetchall.return_value = []
        db.execute = AsyncMock(return_value=mock_result)
        service = mod.APIKeyService(db, self.MOCK_TENANT)
        return service, mod

    @pytest.mark.asyncio
    async def test_create_key(self, key_service):
        """创建密钥返回完整密钥（仅一次）"""
        service, mod = key_service
        result = await service.create_key(
            name="Test App",
            permissions=["orders:read", "menu:read"],
            rate_limit_rps=20,
        )
        assert result["name"] == "Test App"
        assert result["full_key"].startswith("tx_")  # 仅此一次
        assert result["key_prefix"] == result["full_key"][:10]
        assert result["status"] == "active"

    @pytest.mark.asyncio
    async def test_create_key_invalid_permission(self, key_service):
        """非法权限抛出异常"""
        service, mod = key_service
        with pytest.raises(mod.APIKeyPermissionError):
            await service.create_key(name="Bad App", permissions=["invalid:perm"])

    @pytest.mark.asyncio
    async def test_list_keys(self, key_service):
        """列出密钥"""
        service, mod = key_service
        keys = await service.list_keys()
        assert isinstance(keys, list)

    @pytest.mark.asyncio
    async def test_revoke_key_not_found(self, key_service):
        """吊销不存在的密钥抛出异常"""
        import uuid

        service, mod = key_service
        with pytest.raises(mod.APIKeyNotFoundError):
            await service.revoke_key(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_authenticate_invalid_key(self, key_service):
        """无效密钥返回 None"""
        service, mod = key_service
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        result = await mod.APIKeyService.authenticate("tx_invalid_key_123", db)
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# Rate Limiter
# ═══════════════════════════════════════════════════════════════════════════


class TestRateLimiter:
    """Redis 滑动窗口限流器"""

    @pytest.fixture
    def limiter(self):
        mod = _load_module(
            "rate_limiter",
            "shared/apikeys/src/rate_limiter.py",
        )
        return mod.RateLimiter()

    def test_no_redis_raises(self, limiter):
        """未配置 Redis 时抛出 RuntimeError"""
        with pytest.raises(RuntimeError, match="Redis client not configured"):
            import asyncio

            asyncio.run(limiter.check("key-1", 10))


# ═══════════════════════════════════════════════════════════════════════════
# Webhook Service
# ═══════════════════════════════════════════════════════════════════════════


class TestWebhookService:
    """Webhook 订阅与投递服务"""

    MOCK_TENANT = "a0000000-0000-0000-0000-000000000001"

    @pytest.fixture
    def webhook_service(self):
        mod = _load_module(
            "webhook_service",
            "shared/apikeys/src/webhook_service.py",
        )
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_result.fetchall.return_value = []
        db.execute = AsyncMock(return_value=mock_result)
        db.commit = AsyncMock()
        service = mod.WebhookService(db, self.MOCK_TENANT)
        return service, mod

    @pytest.mark.asyncio
    async def test_create_subscription(self, webhook_service):
        """创建 Webhook 订阅"""
        service, mod = webhook_service
        sub = await service.create_subscription(
            url="https://myapp.com/webhook",
            events=["order.paid", "order.created"],
            secret="test-secret",
        )
        assert sub["url"] == "https://myapp.com/webhook"
        assert sub["status"] == "active"
        assert "order.paid" in sub["events"]

    @pytest.mark.asyncio
    async def test_list_subscriptions(self, webhook_service):
        """列出订阅"""
        service, mod = webhook_service
        subs = await service.list_subscriptions()
        assert isinstance(subs, list)

    @pytest.mark.asyncio
    async def test_get_delivery_logs(self, webhook_service):
        """查询投递日志"""
        service, mod = webhook_service
        logs = await service.get_delivery_logs()
        assert isinstance(logs, list)

    def test_sign_payload(self, webhook_service):
        """HMAC-SHA256 签名"""
        service, mod = webhook_service
        sig = service._sign_payload('{"test":1}', "my-secret")
        assert isinstance(sig, str)
        assert len(sig) == 64  # SHA-256 hex

    @pytest.mark.asyncio
    async def test_deliver_event_no_subscribers(self, webhook_service):
        """无匹配订阅时不投递"""
        service, mod = webhook_service
        count = await service.deliver_event("order.paid", {"order_id": "123"})
        assert count == 0
