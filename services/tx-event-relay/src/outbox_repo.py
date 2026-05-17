"""outbox_repo — asyncpg-backed trade_event_outbox 读写.

asyncpg pool 模型 (per memory `feedback_projector_asyncpg_pool_model.md`):
  - 自建 pool min=1 max=3, 不复用 SQLAlchemy async_session_factory
  - shadow 单实例 +3 conn, 远低于 PG max_connections=100

shadow 期间仅 fetch_pending_batch 被调用 (relay log + continue).
W11 follow-up issue #767: 加 mark_delivered() 写真投递路径.
"""
from __future__ import annotations

import os
from typing import Any

import structlog

try:
    import asyncpg
except ImportError:  # pragma: no cover — CI minimal deps fallback
    asyncpg = None  # type: ignore[assignment]

logger = structlog.get_logger(__name__)


# 自建 asyncpg pool 配置 (per memory `feedback_projector_asyncpg_pool_model.md`)
_POOL_MIN_SIZE = 1
_POOL_MAX_SIZE = 3


async def create_pool(dsn: str | None = None) -> Any:
    """创建 asyncpg connection pool (min=1 max=3).

    Args:
        dsn: PostgreSQL DSN. None → 从 DATABASE_URL env 读取.

    Returns:
        asyncpg.Pool 实例.

    Raises:
        RuntimeError: asyncpg 不可用 (CI minimal deps).
    """
    if asyncpg is None:
        raise RuntimeError(
            "asyncpg not installed — tx-event-relay requires asyncpg>=0.29 at runtime"
        )
    if dsn is None:
        dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL env required for tx-event-relay asyncpg pool")
    # asyncpg 不识 postgresql+asyncpg:// SQLAlchemy 方言前缀, rewrite
    if dsn.startswith("postgresql+asyncpg://"):
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    pool = await asyncpg.create_pool(
        dsn=dsn,
        min_size=_POOL_MIN_SIZE,
        max_size=_POOL_MAX_SIZE,
        command_timeout=10.0,
    )
    logger.info(
        "outbox_repo_pool_created",
        min_size=_POOL_MIN_SIZE,
        max_size=_POOL_MAX_SIZE,
    )
    return pool


# fetch_pending_batch SQL (relay 主路径).
# 注: relay worker 走 superuser SA (BYPASSRLS 角色 / 不依赖 RLS), 跨租户 polling
# 不卡单租户. 审计场景在 metadata 字段记录 tenant_id, 不依赖 set_config.
_FETCH_PENDING_SQL = """
    SELECT id, tenant_id, event_type, stream_id, payload, metadata,
           source_service, store_id, causation_id, correlation_id,
           created_at, delivery_attempts, last_error
    FROM trade_event_outbox
    WHERE delivered = FALSE
    ORDER BY created_at ASC
    LIMIT $1
"""


async def fetch_pending_batch(pool: Any, batch_size: int) -> list[dict[str, Any]]:
    """从 trade_event_outbox 拿一批未投递行.

    shadow 期间表预期空 → 返回 []. 0 IO 开销.

    Args:
        pool: asyncpg.Pool.
        batch_size: 每批最多返回行数 (env RELAY_BATCH_SIZE, 默认 100).

    Returns:
        list of dict, 每 row 含 outbox 全字段.
    """
    if pool is None:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(_FETCH_PENDING_SQL, batch_size)
    return [dict(row) for row in rows]


_PENDING_COUNT_SQL = """
    SELECT COUNT(*) AS cnt
    FROM trade_event_outbox
    WHERE delivered = FALSE
"""


async def count_pending(pool: Any) -> int:
    """统计当前 outbox 积压数 (供 /health endpoint).

    relay worker 跨租户 polling, 这里 superuser 角色直接 COUNT.

    Args:
        pool: asyncpg.Pool.

    Returns:
        未投递行数. pool=None 时返回 0.
    """
    if pool is None:
        return 0
    async with pool.acquire() as conn:
        row = await conn.fetchrow(_PENDING_COUNT_SQL)
    return int(row["cnt"]) if row else 0
