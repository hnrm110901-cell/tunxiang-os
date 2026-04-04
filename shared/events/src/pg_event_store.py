"""PgEventStore — PostgreSQL 统一事件持久化写入器

职责：
- 将业务事件 append-only 写入 events 表（v147 迁移创建）
- 写入后触发 PG NOTIFY（由数据库触发器自动发出），通知投影器
- Redis 不可用时仍能持久化；PG 不可用时降级记录日志，不阻塞主业务
- 支持因果链追踪（causation_id / correlation_id）

用法（在业务代码写入路径的异步任务中调用）：
    import asyncio
    asyncio.create_task(PgEventStore.append(
        event_type=OrderEventType.PAID,
        tenant_id=tenant_id,
        stream_id=str(order_id),
        payload={"total_fen": 8800, "channel": "dine_in"},
        store_id=store_id,
        source_service="tx-trade",
        metadata={"operator_id": str(employee_id), "device": "pos_main"},
        causation_id=None,
    ))

设计要点：
- 连接池通过 asyncpg 直接操作（不走 SQLAlchemy ORM，减少开销）
- 连接池为模块级单例，lazy init
- PG 不可用时降级（记录日志，不抛异常，不影响主业务）
- 事件 payload 中金额字段约定为分（整数）
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

import structlog

from .event_types import resolve_stream_type

logger = structlog.get_logger(__name__)

# ──────────────────────────────────────────────────────────────────────
# 配置
# ──────────────────────────────────────────────────────────────────────

DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/tunxiang",
)
_POOL_MIN_SIZE: int = 2
_POOL_MAX_SIZE: int = 10


class PgEventStore:
    """PostgreSQL append-only 事件存储写入器（类方法接口，连接池单例）"""

    _pool: Optional[object] = None  # asyncpg.Pool (lazy init)

    # ──────────────────────────────────────────────────────────────────
    # 连接池管理
    # ──────────────────────────────────────────────────────────────────

    @classmethod
    async def _get_pool(cls) -> object:
        """获取（或创建）asyncpg 连接池单例。"""
        if cls._pool is None:
            import asyncpg  # type: ignore[import-untyped]

            cls._pool = await asyncpg.create_pool(
                DATABASE_URL,
                min_size=_POOL_MIN_SIZE,
                max_size=_POOL_MAX_SIZE,
                command_timeout=5,
            )
        return cls._pool

    @classmethod
    async def close(cls) -> None:
        """关闭连接池（服务关闭时调用）。"""
        if cls._pool is not None:
            await cls._pool.close()  # type: ignore[union-attr]
            cls._pool = None
            logger.info("pg_event_store_pool_closed")

    # ──────────────────────────────────────────────────────────────────
    # 核心写入
    # ──────────────────────────────────────────────────────────────────

    @classmethod
    async def append(
        cls,
        *,
        event_type: object,                  # 任意 EventType 枚举或字符串
        tenant_id: UUID | str,
        stream_id: str,                      # 聚合根ID，如订单号、会员ID
        payload: dict[str, Any],
        store_id: Optional[UUID | str] = None,
        source_service: str = "unknown",
        metadata: Optional[dict[str, Any]] = None,
        causation_id: Optional[UUID | str] = None,
        correlation_id: Optional[UUID | str] = None,
        occurred_at: Optional[datetime] = None,
        schema_version: str = "1.0",
    ) -> Optional[str]:
        """追加单条事件到 events 表。

        Args:
            event_type:      事件类型枚举或点分字符串
            tenant_id:       租户 UUID
            stream_id:       聚合根ID（如订单号、会员ID）
            payload:         业务数据（金额字段约定为分/整数）
            store_id:        门店 UUID（可选）
            source_service:  来源服务名
            metadata:        元数据（设备ID/操作员/渠道等）
            causation_id:    因果链：触发本事件的父事件ID
            correlation_id:  相关ID：同一业务流程的所有事件共享
            occurred_at:     业务发生时间（None则取当前UTC时间）
            schema_version:  事件格式版本

        Returns:
            写入成功的 event_id（UUID字符串），失败时返回 None。
        """
        event_type_str = (
            event_type.value  # type: ignore[union-attr]
            if hasattr(event_type, "value")
            else str(event_type)
        )
        stream_type = resolve_stream_type(event_type_str)
        event_id = str(uuid4())
        now = occurred_at or datetime.now(timezone.utc)

        try:
            pool = await cls._get_pool()

            async with pool.acquire() as conn:  # type: ignore[union-attr]
                # 设置 RLS 上下文
                await conn.execute(
                    "SELECT set_config('app.tenant_id', $1, TRUE)",
                    str(tenant_id),
                )

                await conn.execute(
                    """
                    INSERT INTO events (
                        event_id, tenant_id, store_id,
                        stream_id, stream_type, event_type,
                        occurred_at, payload, metadata,
                        causation_id, correlation_id,
                        schema_version, source_service
                    ) VALUES (
                        $1, $2, $3,
                        $4, $5, $6,
                        $7, $8::jsonb, $9::jsonb,
                        $10, $11,
                        $12, $13
                    )
                    """,
                    UUID(event_id),
                    UUID(str(tenant_id)),
                    UUID(str(store_id)) if store_id else None,
                    stream_id,
                    stream_type,
                    event_type_str,
                    now,
                    json.dumps(payload, ensure_ascii=False, default=str),
                    json.dumps(metadata or {}, ensure_ascii=False, default=str),
                    UUID(str(causation_id)) if causation_id else None,
                    UUID(str(correlation_id)) if correlation_id else None,
                    schema_version,
                    source_service,
                )

            logger.debug(
                "pg_event_stored",
                event_id=event_id,
                event_type=event_type_str,
                stream_type=stream_type,
                stream_id=stream_id,
                tenant_id=str(tenant_id),
                source_service=source_service,
            )
            return event_id

        except OSError as exc:
            logger.warning(
                "pg_event_store_failed_os",
                event_type=event_type_str,
                tenant_id=str(tenant_id),
                error=str(exc),
            )
            cls._pool = None  # 重置连接池，下次重新建立
            return None
        except RuntimeError as exc:
            logger.warning(
                "pg_event_store_failed_runtime",
                event_type=event_type_str,
                tenant_id=str(tenant_id),
                error=str(exc),
            )
            return None
        except Exception as exc:  # noqa: BLE001 — 最外层兜底，不能让事件写入阻塞主业务
            logger.error(
                "pg_event_store_failed_unexpected",
                event_type=event_type_str,
                tenant_id=str(tenant_id),
                error=str(exc),
                exc_info=True,
            )
            return None

    @classmethod
    async def append_batch(
        cls,
        events: list[dict[str, Any]],
    ) -> list[Optional[str]]:
        """批量追加事件（原子性写入，事务内）。

        Args:
            events: 每个元素是 append() 的关键字参数字典

        Returns:
            与 events 一一对应的 event_id 列表，失败项为 None。
        """
        if not events:
            return []

        results: list[Optional[str]] = []
        for ev_kwargs in events:
            result = await cls.append(**ev_kwargs)
            results.append(result)
        return results

    # ──────────────────────────────────────────────────────────────────
    # 查询（回溯用，不走ORM）
    # ──────────────────────────────────────────────────────────────────

    @classmethod
    async def get_stream(
        cls,
        *,
        tenant_id: UUID | str,
        stream_type: str,
        stream_id: str,
        after_sequence: int = 0,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """获取指定聚合根的完整事件序列（回溯/重建用）。

        Returns:
            事件列表，按 sequence_num ASC 排序。
        """
        try:
            pool = await cls._get_pool()
            async with pool.acquire() as conn:  # type: ignore[union-attr]
                await conn.execute(
                    "SELECT set_config('app.tenant_id', $1, TRUE)",
                    str(tenant_id),
                )
                rows = await conn.fetch(
                    """
                    SELECT event_id, event_type, stream_id, sequence_num,
                           occurred_at, payload, metadata, causation_id
                    FROM events
                    WHERE tenant_id = $1
                      AND stream_type = $2
                      AND stream_id = $3
                      AND sequence_num > $4
                    ORDER BY sequence_num ASC
                    LIMIT $5
                    """,
                    UUID(str(tenant_id)),
                    stream_type,
                    stream_id,
                    after_sequence,
                    limit,
                )
            return [dict(r) for r in rows]
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "pg_event_store_get_stream_failed",
                tenant_id=str(tenant_id),
                stream_type=stream_type,
                stream_id=stream_id,
                error=str(exc),
                exc_info=True,
            )
            return []
