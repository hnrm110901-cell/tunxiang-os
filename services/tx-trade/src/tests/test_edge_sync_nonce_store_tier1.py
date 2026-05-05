"""edge_sync_nonce_store Tier 1 测试

第二轮 review P1-1 修复：进程内 dict 防重放在多副本下失效，已抽象到
EdgeSyncNonceStore 接口 + InProcess + Redis 实现。本测试验证：
  1. InProcessNonceStore 基本 seen_and_mark + GC 行为
  2. 多副本场景：两个独立 InProcess 实例不共享 nonce → 演示问题根源
  3. RedisNonceStore SETNX 原子语义（用 mock）
  4. 工厂函数按 env 切换正确实现
  5. 生产 fail-closed 路径
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

# 把 services/tx-trade/src 加 path
_SRC = str(Path(__file__).resolve().parent.parent)
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from edge_sync_nonce_store import (  # noqa: E402
    EdgeSyncNonceStore,
    InProcessNonceStore,
    RedisNonceStore,
    get_nonce_store,
    reset_nonce_store_for_testing,
)


@pytest.fixture(autouse=True)
def _reset_store():
    """每个测试前清 singleton + env，避免跨测试污染。"""
    reset_nonce_store_for_testing()
    yield
    reset_nonce_store_for_testing()


class TestInProcessNonceStore:
    @pytest.mark.asyncio
    async def test_first_seen_returns_false(self):
        s = InProcessNonceStore()
        assert await s.seen_and_mark("store-1:nonce-a", ttl_seconds=300) is False

    @pytest.mark.asyncio
    async def test_second_seen_returns_true(self):
        s = InProcessNonceStore()
        await s.seen_and_mark("store-1:nonce-a", ttl_seconds=300)
        assert await s.seen_and_mark("store-1:nonce-a", ttl_seconds=300) is True

    @pytest.mark.asyncio
    async def test_different_nonces_isolated(self):
        s = InProcessNonceStore()
        await s.seen_and_mark("store-1:nonce-a", ttl_seconds=300)
        # 不同 nonce 应独立
        assert await s.seen_and_mark("store-1:nonce-b", ttl_seconds=300) is False
        assert await s.seen_and_mark("store-2:nonce-a", ttl_seconds=300) is False

    @pytest.mark.asyncio
    async def test_ttl_expiry(self):
        """超过 ttl 后同 nonce 被视为新（GC 清理）。"""
        import time as _time

        s = InProcessNonceStore()
        await s.seen_and_mark("store-1:nonce-a", ttl_seconds=300)

        # 模拟过期：把 _seen 内的 ts 改到很久以前
        s._seen["store-1:nonce-a"] = _time.time() - 1000  # 1000s 前

        # 再 mark 同 nonce，GC 应清掉旧记录，新请求被视为首次
        assert await s.seen_and_mark("store-1:nonce-a", ttl_seconds=300) is False


class TestMultiReplicaProblem:
    """演示问题根源 + 验证 Redis 是正确解。"""

    @pytest.mark.asyncio
    async def test_two_inprocess_stores_dont_share(self):
        """两个独立 InProcess 实例（代表两个 pod）—— 同 nonce 打两次都通过 = 防重放失效。

        这就是为什么生产必须用 RedisNonceStore。
        """
        pod_a = InProcessNonceStore()
        pod_b = InProcessNonceStore()

        # 攻击者把同一签名同时打到两个 pod
        replayed_on_a = await pod_a.seen_and_mark("store-1:replay-nonce", 300)
        replayed_on_b = await pod_b.seen_and_mark("store-1:replay-nonce", 300)

        # 两个都返 False（都视为首次）→ 重放被放大 = 失效
        assert replayed_on_a is False
        assert replayed_on_b is False, (
            "InProcess 多副本下防重放失效 — 这是设计取舍，必须配 Redis 才共享。"
            "本测试演示问题根源，确保团队理解为何 EDGE_SYNC_NONCE_REDIS_URL 在生产必须配。"
        )


class TestRedisNonceStoreContract:
    """RedisNonceStore 与 redis.asyncio SETNX EX 契约（用 mock 验证调用形态）。"""

    @pytest.mark.asyncio
    async def test_first_seen_calls_set_nx_ex(self):
        s = RedisNonceStore("redis://test")
        mock_client = mock.AsyncMock()
        mock_client.set = mock.AsyncMock(return_value=True)  # SETNX 成功 = 未见过
        s._client = mock_client

        result = await s.seen_and_mark("store-1:nonce-a", ttl_seconds=300)
        assert result is False  # 未见过

        mock_client.set.assert_awaited_once()
        call_kwargs = mock_client.set.await_args
        # 应该用 nx=True (SETNX) 和 ex=300 (TTL)
        assert call_kwargs.kwargs.get("nx") is True
        assert call_kwargs.kwargs.get("ex") == 300

    @pytest.mark.asyncio
    async def test_replay_returns_true(self):
        s = RedisNonceStore("redis://test")
        mock_client = mock.AsyncMock()
        # SETNX 失败（key 已存在） → set() 返回 None/False
        mock_client.set = mock.AsyncMock(return_value=None)
        s._client = mock_client

        result = await s.seen_and_mark("store-1:nonce-a", ttl_seconds=300)
        assert result is True  # 已见过 = 重放

    @pytest.mark.asyncio
    async def test_redis_failure_raises_runtime_error(self):
        """Redis 连不上 → RuntimeError → router fail-closed 503。"""
        s = RedisNonceStore("redis://nonexistent")
        mock_client = mock.AsyncMock()
        mock_client.set = mock.AsyncMock(side_effect=ConnectionError("redis down"))
        s._client = mock_client

        with pytest.raises(RuntimeError, match="nonce store backend error"):
            await s.seen_and_mark("store-1:nonce-a", ttl_seconds=300)

    @pytest.mark.asyncio
    async def test_full_key_uses_prefix(self):
        s = RedisNonceStore("redis://test", key_prefix="custom:")
        mock_client = mock.AsyncMock()
        mock_client.set = mock.AsyncMock(return_value=True)
        s._client = mock_client

        await s.seen_and_mark("nonce-1", ttl_seconds=60)
        # 第一个 positional arg 是 full key
        full_key = mock_client.set.await_args.args[0]
        assert full_key == "custom:nonce-1"

    def test_init_rejects_empty_url(self):
        with pytest.raises(ValueError):
            RedisNonceStore("")


class TestFactory:
    @pytest.mark.asyncio
    async def test_returns_inprocess_when_no_redis_url(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            store = get_nonce_store()
            assert isinstance(store, InProcessNonceStore)

    @pytest.mark.asyncio
    async def test_returns_redis_when_url_set(self):
        with mock.patch.dict(
            os.environ,
            {"EDGE_SYNC_NONCE_REDIS_URL": "redis://localhost:6379/0"},
            clear=True,
        ):
            store = get_nonce_store()
            assert isinstance(store, RedisNonceStore)

    @pytest.mark.asyncio
    async def test_singleton_returns_same_instance(self):
        with mock.patch.dict(
            os.environ,
            {"EDGE_SYNC_NONCE_REDIS_URL": "redis://test"},
            clear=True,
        ):
            a = get_nonce_store()
            b = get_nonce_store()
            assert a is b

    @pytest.mark.asyncio
    async def test_production_requires_redis_when_hmac_required(self):
        """生产 + EDGE_SYNC_HMAC_REQUIRED=true 但无 Redis URL → raise（防 silent 降级）。"""
        with mock.patch.dict(
            os.environ,
            {"TX_ENV": "production", "EDGE_SYNC_HMAC_REQUIRED": "true"},
            clear=True,
        ):
            with pytest.raises(RuntimeError, match="EDGE_SYNC_NONCE_REDIS_URL 未配置"):
                get_nonce_store()

    @pytest.mark.asyncio
    async def test_production_allows_inprocess_with_explicit_optout(self):
        """生产 + 不要求 hmac required + 显式 ALLOW_INPROCESS=true → 允许（cutover 前过渡）。"""
        with mock.patch.dict(
            os.environ,
            {
                "TX_ENV": "production",
                "EDGE_SYNC_NONCE_ALLOW_INPROCESS": "true",
            },
            clear=True,
        ):
            store = get_nonce_store()
            assert isinstance(store, InProcessNonceStore)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
