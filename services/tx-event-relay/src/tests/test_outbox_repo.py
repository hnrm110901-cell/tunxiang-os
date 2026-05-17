"""Unit tests for outbox_repo (asyncpg pool + fetch_pending_batch)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.tx_event_relay.src import outbox_repo
from services.tx_event_relay.src.outbox_repo import (
    _POOL_MAX_SIZE,
    _POOL_MIN_SIZE,
    count_pending,
    fetch_pending_batch,
)


def test_pool_sizes_match_memory_pattern():
    """asyncpg pool min=1 max=3 per memory `feedback_projector_asyncpg_pool_model.md`."""
    assert _POOL_MIN_SIZE == 1
    assert _POOL_MAX_SIZE == 3


@pytest.mark.asyncio
async def test_fetch_pending_batch_returns_empty_when_pool_none():
    """pool=None (degraded startup) → fetch_pending_batch 返 [] 不崩."""
    rows = await fetch_pending_batch(pool=None, batch_size=100)
    assert rows == []


@pytest.mark.asyncio
async def test_count_pending_returns_zero_when_pool_none():
    """pool=None → count_pending 返 0 (供 /health degraded)."""
    count = await count_pending(pool=None)
    assert count == 0


@pytest.mark.asyncio
async def test_fetch_pending_batch_invokes_asyncpg_fetch():
    """fetch_pending_batch 走 pool.acquire().fetch() 路径 + 转 dict.

    Mock pool 验证 SQL 调用 + LIMIT 参数 + 返回 dict 列表.
    """
    mock_rows = [
        {"id": "uuid1", "event_type": "ORDER.PAID", "stream_id": "order-1"},
        {"id": "uuid2", "event_type": "DISCOUNT.APPLIED", "stream_id": "order-1"},
    ]

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=mock_rows)

    # async context manager mock
    mock_acquire_ctx = AsyncMock()
    mock_acquire_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=mock_acquire_ctx)

    rows = await fetch_pending_batch(pool=mock_pool, batch_size=50)
    assert len(rows) == 2
    assert rows[0]["event_type"] == "ORDER.PAID"
    # 验证 LIMIT $1 = 50
    mock_conn.fetch.assert_awaited_once()
    call_args = mock_conn.fetch.await_args
    assert call_args.args[1] == 50, "batch_size 必须作为 LIMIT 参数"


@pytest.mark.asyncio
async def test_count_pending_invokes_asyncpg_fetchrow():
    """count_pending 走 pool.acquire().fetchrow() + 转 int."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value={"cnt": 42})

    mock_acquire_ctx = AsyncMock()
    mock_acquire_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=mock_acquire_ctx)

    count = await count_pending(pool=mock_pool)
    assert count == 42


@pytest.mark.asyncio
async def test_create_pool_raises_without_dsn(monkeypatch):
    """DATABASE_URL 缺 → create_pool 抛 RuntimeError (防 silent degraded)."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    # asyncpg=None 兜底 (CI minimal deps), 优先撞 asyncpg check
    with patch.object(outbox_repo, "asyncpg", None):
        with pytest.raises(RuntimeError, match="asyncpg not installed"):
            await outbox_repo.create_pool()


@pytest.mark.asyncio
async def test_create_pool_rewrites_sqlalchemy_dsn(monkeypatch):
    """DSN 含 postgresql+asyncpg:// 前缀 → rewrite 为纯 postgresql://.

    asyncpg 不识 SQLAlchemy 方言前缀, 否则连接失败.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)

    captured = {}

    async def fake_create_pool(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    mock_asyncpg = MagicMock()
    mock_asyncpg.create_pool = fake_create_pool

    with patch.object(outbox_repo, "asyncpg", mock_asyncpg):
        await outbox_repo.create_pool(dsn="postgresql+asyncpg://u:p@h:5432/db")

    assert captured["dsn"] == "postgresql://u:p@h:5432/db", "asyncpg DSN 必须 strip SQLAlchemy 方言前缀"
    assert captured["min_size"] == 1
    assert captured["max_size"] == 3
