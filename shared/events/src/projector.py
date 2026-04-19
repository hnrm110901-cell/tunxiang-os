"""ProjectorBase — 事件投影器基类

投影器（Projector）职责：
- 监听 PG NOTIFY "event_inserted" 通知
- 从 events 表读取新事件
- 更新对应的物化视图（mv_*）
- 记录消费进度到 projector_checkpoints

设计原则：
- 每个投影器有唯一名称（projector_name）
- 支持从任意位置重播（rebuild 从头重建视图）
- 视图损坏可完全重建，不依赖外部状态
- 多投影器可并发运行，互不影响

使用示例：
    class DiscountHealthProjector(ProjectorBase):
        name = "discount_health"
        event_types = {"discount.applied", "discount.authorized", "discount.revoked"}

        async def handle(self, event: dict, conn: asyncpg.Connection) -> None:
            # 更新 mv_discount_health
            ...

    projector = DiscountHealthProjector(tenant_id=uuid)
    await projector.run()  # 启动监听循环
"""

from __future__ import annotations

import asyncio
import json
import os
from abc import ABC, abstractmethod
from typing import Any, Optional, Set
from uuid import UUID

import structlog

logger = structlog.get_logger(__name__)

DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/tunxiang",
)

_BATCH_SIZE = 100  # 每批处理事件数
_POLL_INTERVAL = 5.0  # 无通知时轮询间隔（秒）
_NOTIFY_CHANNEL = "event_inserted"


class ProjectorBase(ABC):
    """事件投影器抽象基类

    子类必须定义：
        name:        投影器唯一名称（对应 projector_checkpoints.projector_name）
        event_types: 关注的事件类型集合（空集=监听所有）

    子类必须实现：
        handle(event, conn):  处理单条事件，更新物化视图
    """

    name: str = ""
    event_types: Set[str] = set()  # 空集表示监听所有事件类型

    def __init__(self, tenant_id: UUID | str) -> None:
        self.tenant_id = UUID(str(tenant_id))
        self._pool: Optional[object] = None
        self._running = False

    # ──────────────────────────────────────────────────────────────────
    # 抽象接口
    # ──────────────────────────────────────────────────────────────────

    @abstractmethod
    async def handle(self, event: dict[str, Any], conn: object) -> None:
        """处理单条事件，更新对应物化视图。

        Args:
            event:  事件字典，包含 event_id/event_type/payload 等字段
            conn:   asyncpg 连接（已设置 RLS 上下文）
        """
        ...

    # ──────────────────────────────────────────────────────────────────
    # 运行
    # ──────────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """启动投影器监听循环（阻塞，直到 stop() 被调用）。"""
        import asyncpg  # type: ignore[import-untyped]

        self._running = True
        self._pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)

        logger.info(
            "projector_started",
            name=self.name,
            tenant_id=str(self.tenant_id),
            event_types=list(self.event_types) if self.event_types else "all",
        )

        try:
            # 先处理已积压的事件（从上次检查点开始）
            await self._process_backlog()

            # 监听 PG NOTIFY
            async with self._pool.acquire() as conn:  # type: ignore[union-attr]
                await conn.execute(f"LISTEN {_NOTIFY_CHANNEL}")

                while self._running:
                    try:
                        # 等待通知（超时后主动轮询）
                        notification = await asyncio.wait_for(
                            conn.wait_for_notification(),
                            timeout=_POLL_INTERVAL,
                        )
                        if notification:
                            await self._process_backlog()
                    except asyncio.TimeoutError:
                        # 超时正常，主动轮询一次
                        await self._process_backlog()
                    except asyncio.CancelledError:
                        break
                    except Exception as exc:  # noqa: BLE001
                        logger.error(
                            "projector_loop_error",
                            name=self.name,
                            error=str(exc),
                            exc_info=True,
                        )
                        await asyncio.sleep(1)  # 短暂等待后重试
        finally:
            if self._pool:
                await self._pool.close()  # type: ignore[union-attr]
            logger.info("projector_stopped", name=self.name)

    async def stop(self) -> None:
        """停止投影器（优雅关闭）。"""
        self._running = False

    # ──────────────────────────────────────────────────────────────────
    # 重建（视图损坏时从事件流完整重建）
    # ──────────────────────────────────────────────────────────────────

    async def rebuild(self) -> int:
        """从事件存储完全重建物化视图。

        Returns:
            处理的事件总数。
        """
        import asyncpg  # type: ignore[import-untyped]

        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        total = 0

        try:
            # 重置检查点
            async with pool.acquire() as conn:  # type: ignore
                await conn.execute(
                    "SELECT set_config('app.tenant_id', $1, TRUE)",
                    str(self.tenant_id),
                )
                await conn.execute(
                    """
                    INSERT INTO projector_checkpoints
                        (projector_name, tenant_id, last_event_id, events_processed, last_rebuilt_at)
                    VALUES ($1, $2, NULL, 0, NOW())
                    ON CONFLICT (projector_name, tenant_id)
                    DO UPDATE SET last_event_id = NULL, events_processed = 0, last_rebuilt_at = NOW()
                    """,
                    self.name,
                    self.tenant_id,
                )

            # 从头重播
            total = await self._process_backlog(pool=pool)
            logger.info(
                "projector_rebuilt",
                name=self.name,
                tenant_id=str(self.tenant_id),
                total_events=total,
            )
        finally:
            await pool.close()

        return total

    # ──────────────────────────────────────────────────────────────────
    # 内部：积压事件处理
    # ──────────────────────────────────────────────────────────────────

    async def _process_backlog(self, pool: Optional[object] = None) -> int:
        """处理从上次检查点到最新的所有积压事件。

        Returns:
            本次处理的事件数。
        """
        pool = pool or self._pool
        total = 0

        while True:
            batch = await self._fetch_next_batch(pool)
            if not batch:
                break

            async with pool.acquire() as conn:  # type: ignore
                await conn.execute(
                    "SELECT set_config('app.tenant_id', $1, TRUE)",
                    str(self.tenant_id),
                )
                async with conn.transaction():
                    for row in batch:
                        event = dict(row)
                        event["payload"] = (
                            json.loads(event["payload"]) if isinstance(event["payload"], str) else event["payload"]
                        )
                        event["metadata"] = (
                            json.loads(event["metadata"])
                            if isinstance(event["metadata"], str)
                            else (event.get("metadata") or {})
                        )
                        try:
                            await self.handle(event, conn)
                        except Exception as exc:  # noqa: BLE001
                            logger.error(
                                "projector_handle_error",
                                name=self.name,
                                event_id=str(event.get("event_id")),
                                event_type=event.get("event_type"),
                                error=str(exc),
                                exc_info=True,
                            )

                    # 更新检查点
                    last = batch[-1]
                    await conn.execute(
                        """
                        INSERT INTO projector_checkpoints
                            (projector_name, tenant_id, last_event_id, last_occurred_at,
                             events_processed, updated_at)
                        VALUES ($1, $2, $3, $4, $5, NOW())
                        ON CONFLICT (projector_name, tenant_id)
                        DO UPDATE SET
                            last_event_id = $3,
                            last_occurred_at = $4,
                            events_processed = projector_checkpoints.events_processed + $5,
                            updated_at = NOW()
                        """,
                        self.name,
                        self.tenant_id,
                        last["event_id"],
                        last["occurred_at"],
                        len(batch),
                    )

            total += len(batch)
            if len(batch) < _BATCH_SIZE:
                break

        return total

    async def _fetch_next_batch(self, pool: object) -> list[dict]:
        """从 events 表拉取下一批未消费事件。"""
        async with pool.acquire() as conn:  # type: ignore
            await conn.execute(
                "SELECT set_config('app.tenant_id', $1, TRUE)",
                str(self.tenant_id),
            )

            # 获取上次检查点
            checkpoint = await conn.fetchrow(
                """
                SELECT last_occurred_at, last_event_id
                FROM projector_checkpoints
                WHERE projector_name = $1 AND tenant_id = $2
                """,
                self.name,
                self.tenant_id,
            )

            last_occurred_at = checkpoint["last_occurred_at"] if checkpoint else None
            last_event_id = checkpoint["last_event_id"] if checkpoint else None

            # 构造事件类型过滤条件
            type_filter = ""
            params: list[Any] = [self.tenant_id]
            if self.event_types:
                params.append(list(self.event_types))
                type_filter = f"AND event_type = ANY(${len(params)})"

            # 时间过滤
            time_clause = ""
            if last_occurred_at:
                params.append(last_occurred_at)
                params.append(str(last_event_id) if last_event_id else "")
                time_clause = (
                    f"AND (occurred_at > ${len(params) - 1} OR "
                    f"(occurred_at = ${len(params) - 1} AND event_id::TEXT > ${len(params)}))"
                )

            params.append(_BATCH_SIZE)

            rows = await conn.fetch(
                f"""
                SELECT event_id, event_type, stream_id, stream_type,
                       store_id, occurred_at, payload, metadata, causation_id
                FROM events
                WHERE tenant_id = $1
                  {type_filter}
                  {time_clause}
                ORDER BY occurred_at ASC, event_id ASC
                LIMIT ${len(params)}
                """,
                *params,
            )

        return [dict(r) for r in rows]
