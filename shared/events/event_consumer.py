"""MemberEventConsumer — Redis Stream 消费器（Consumer Group 模式）

设计要点：
- Consumer Group 确保每条消息只被一个消费者处理一次
- 处理失败时写入 Dead Letter Queue（member_events_dlq）
- 支持从指定 ID 重放事件（运维用）
- 禁止 broad except，所有异常类型明确列举
"""

from __future__ import annotations

import json
from typing import Awaitable, Callable, Optional
from uuid import UUID

import structlog

from .event_publisher import STREAM_KEY, MemberEventPublisher
from .member_events import MemberEvent, MemberEventType

logger = structlog.get_logger(__name__)

DLQ_STREAM_KEY: str = "member_events_dlq"


class MemberEventConsumer:
    """Redis Stream 消费器

    Args:
        group_name:    消费者组名称（每个微服务用不同的组名）
        consumer_name: 消费者名称（同一组内可有多个消费者实例）

    示例：
        consumer = MemberEventConsumer("rfm_updater", "rfm_realtime")
        redis = await MemberEventPublisher.get_redis()
        await consumer.ensure_group(redis)
        await consumer.consume(handler_func)
    """

    def __init__(self, group_name: str, consumer_name: str) -> None:
        self.group_name = group_name
        self.consumer_name = consumer_name

    async def ensure_group(self, redis: "aioredis.Redis") -> None:  # type: ignore[name-defined]
        """确保消费者组存在，不存在则创建。

        id="0" 表示从 Stream 最早的消息开始消费（若要只消费新消息改为 "$"）。
        mkstream=True 表示 Stream 不存在时自动创建。
        BUSYGROUP 错误表示组已存在，忽略即可。
        """
        import redis.asyncio as aioredis

        try:
            await redis.xgroup_create(
                STREAM_KEY,
                self.group_name,
                id="0",
                mkstream=True,
            )
            logger.info(
                "consumer_group_created",
                group=self.group_name,
                stream=STREAM_KEY,
            )
        except aioredis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def consume(
        self,
        handler: Callable[[MemberEvent], Awaitable[None]],
        batch_size: int = 10,
        block_ms: int = 1000,
    ) -> None:
        """持续消费事件（阻塞式循环，应在独立 asyncio Task 中运行）。

        流程：
            1. xreadgroup 拉取未处理消息（">" 表示只读未分配的新消息）
            2. 反序列化为 MemberEvent
            3. 调用 handler 处理
            4. xack 确认（ACK 后消息从 PEL 移除）
            5. 处理失败时写入 DLQ

        Args:
            handler:    事件处理回调（async），接收 MemberEvent
            batch_size: 每次 xreadgroup 拉取的最大消息数
            block_ms:   无新消息时阻塞等待的毫秒数（0 表示不阻塞）
        """
        import redis.asyncio as aioredis

        redis = await MemberEventPublisher.get_redis()
        await self.ensure_group(redis)

        logger.info(
            "consumer_loop_started",
            group=self.group_name,
            consumer=self.consumer_name,
            batch_size=batch_size,
        )

        while True:
            try:
                messages: Optional[list] = await redis.xreadgroup(
                    groupname=self.group_name,
                    consumername=self.consumer_name,
                    streams={STREAM_KEY: ">"},
                    count=batch_size,
                    block=block_ms,
                )
            except aioredis.ResponseError as exc:
                logger.error(
                    "consumer_xreadgroup_error",
                    group=self.group_name,
                    error=str(exc),
                    exc_info=True,
                )
                # 短暂等待后重试（避免错误风暴）
                import asyncio

                await asyncio.sleep(2)
                continue
            except OSError as exc:
                logger.warning(
                    "consumer_redis_connection_lost",
                    group=self.group_name,
                    error=str(exc),
                )
                import asyncio

                await asyncio.sleep(5)
                # 重置连接
                MemberEventPublisher._redis = None
                redis = await MemberEventPublisher.get_redis()
                await self.ensure_group(redis)
                continue

            if not messages:
                continue

            for _stream, entries in messages:
                for entry_id, fields in entries:
                    await self._process_entry(redis, entry_id, fields, handler)

    async def _process_entry(
        self,
        redis: "aioredis.Redis",  # type: ignore[name-defined]
        entry_id: str,
        fields: dict[str, str],
        handler: Callable[[MemberEvent], Awaitable[None]],
    ) -> None:
        """处理单条 Stream 消息。

        成功后 XACK；失败后写 DLQ 并 XACK（避免无限重试阻塞队列）。
        """
        event: Optional[MemberEvent] = None
        try:
            event = _deserialize_event(fields)
            await handler(event)
            await redis.xack(STREAM_KEY, self.group_name, entry_id)
            logger.debug(
                "consumer_event_acked",
                entry_id=entry_id,
                event_type=fields.get("event_type"),
                group=self.group_name,
            )
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            # 反序列化失败：数据格式错误，直接送 DLQ
            logger.error(
                "consumer_event_deserialize_failed",
                entry_id=entry_id,
                fields=fields,
                error=str(exc),
                exc_info=True,
            )
            await self._send_to_dlq(redis, entry_id, fields, str(exc), "deserialize_failed")
            await redis.xack(STREAM_KEY, self.group_name, entry_id)
        except (OSError, RuntimeError) as exc:
            # 处理器业务异常（如 DB 连接失败）：送 DLQ，ACK 避免卡队列
            logger.error(
                "consumer_event_handler_failed",
                entry_id=entry_id,
                event_type=fields.get("event_type"),
                group=self.group_name,
                error=str(exc),
                exc_info=True,
            )
            await self._send_to_dlq(redis, entry_id, fields, str(exc), "handler_failed")
            await redis.xack(STREAM_KEY, self.group_name, entry_id)

    async def _send_to_dlq(
        self,
        redis: "aioredis.Redis",  # type: ignore[name-defined]
        original_entry_id: str,
        fields: dict[str, str],
        error_msg: str,
        failure_reason: str,
    ) -> None:
        """将失败事件写入 Dead Letter Queue（member_events_dlq）。"""
        from datetime import datetime, timezone

        dlq_fields: dict[str, str] = {
            **fields,
            "original_entry_id": original_entry_id,
            "failure_reason": failure_reason,
            "error_message": error_msg,
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "consumer_group": self.group_name,
            "consumer_name": self.consumer_name,
        }

        try:
            await redis.xadd(
                DLQ_STREAM_KEY,
                dlq_fields,
                maxlen=50_000,
                approximate=True,
            )
            logger.warning(
                "consumer_event_sent_to_dlq",
                original_entry_id=original_entry_id,
                failure_reason=failure_reason,
                dlq_stream=DLQ_STREAM_KEY,
            )
        except (OSError, RuntimeError) as exc:
            # DLQ 写入失败只记录日志，不再抛出（避免无限递归）
            logger.error(
                "consumer_dlq_write_failed",
                original_entry_id=original_entry_id,
                error=str(exc),
            )

    async def replay_from(
        self,
        start_id: str,
        handler: Callable[[MemberEvent], Awaitable[None]],
        batch_size: int = 100,
    ) -> int:
        """从指定 Stream ID 开始重放事件（运维用途）。

        直接使用 XRANGE 读取（不经过 Consumer Group），
        适用于数据修复、补偿计算场景。

        Args:
            start_id:   起始 Stream entry ID（含），格式如 "1699000000000-0"
                        传入 "-" 表示从头开始
            handler:    事件处理回调
            batch_size: 每批读取条数

        Returns:
            实际处理的事件总数
        """
        redis = await MemberEventPublisher.get_redis()
        total = 0
        cursor = start_id

        logger.info(
            "consumer_replay_started",
            start_id=start_id,
            group=self.group_name,
        )

        while True:
            entries = await redis.xrange(
                STREAM_KEY,
                min=cursor,
                max="+",
                count=batch_size,
            )

            if not entries:
                break

            for entry_id, fields in entries:
                try:
                    event = _deserialize_event(fields)
                    await handler(event)
                    total += 1
                except (ValueError, KeyError, json.JSONDecodeError, OSError, RuntimeError) as exc:
                    logger.error(
                        "consumer_replay_entry_failed",
                        entry_id=entry_id,
                        error=str(exc),
                        exc_info=True,
                    )

            # 下一批从最后一条的下一个 ID 开始
            last_id = entries[-1][0]
            # 将最后 ID 的序号 +1，避免重复处理最后一条
            ts, seq = last_id.rsplit("-", 1)
            cursor = f"{ts}-{int(seq) + 1}"

            if len(entries) < batch_size:
                break

        logger.info(
            "consumer_replay_completed",
            start_id=start_id,
            total_processed=total,
        )
        return total


def _deserialize_event(fields: dict[str, str]) -> MemberEvent:
    """将 Redis Stream fields dict 反序列化为 MemberEvent。

    Raises:
        KeyError: 必填字段缺失
        ValueError: UUID 解析失败 / 枚举值不合法
        json.JSONDecodeError: event_data JSON 格式错误
    """
    event_type = MemberEventType(fields["event_type"])
    tenant_id = UUID(fields["tenant_id"])
    customer_id = UUID(fields["customer_id"])
    event_data: dict = json.loads(fields.get("event_data", "{}"))

    from datetime import datetime, timezone

    occurred_at_str: str = fields.get("occurred_at", datetime.now(timezone.utc).isoformat())
    try:
        occurred_at = datetime.fromisoformat(occurred_at_str)
    except ValueError:
        occurred_at = datetime.now(timezone.utc)

    return MemberEvent(
        event_type=event_type,
        tenant_id=tenant_id,
        customer_id=customer_id,
        event_data=event_data,
        event_id=fields.get("event_id", ""),
        occurred_at=occurred_at,
        source_service=fields.get("source_service", "unknown"),
    )
