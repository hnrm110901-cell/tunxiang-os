"""EventRelay — PG events 表 → EventBus 的 Outbox Relay (T5.1.5).

职责:
1. 周期扫描 events 表 (sequence_num > last_cursor_sequence)
2. 反序列化 payload 为 OntologyEvent 子类 (via schema_registry)
3. 通过 EventBus.publish() 转发到 Redis Streams
4. 更新 event_outbox_cursor 游标

语义:
- 至少一次 (at-least-once): publish 成功 + cursor 更新后才算投递
- 部分批次失败时, 游标只前进到最后成功的一条
- 毒丸 (未注册 event_type) 跳过但游标前进, 避免卡死
- 幂等: 第二次 run_once() 若无新事件返回 0

分层:
- OutboxReader 抽象层 — 让生产用 PgOutboxReader, 测试用 FakeOutboxReader
- EventRelay 不直接写 SQL, 保持可测 + 可替换存储

APScheduler 注册 (scheduler.py 中, 另一 session 稳定后接入):
    scheduler.add_job(relay.run_once, 'interval', seconds=10)
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

import structlog

from shared.events.schemas.base import OntologyEvent

from .event_bus import EventBus, EventEnvelope

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class PendingEvent:
    """events 表单行的抽象表达. OutboxReader 读出的数据结构."""

    event_id: str
    sequence_num: int
    aggregate_id: str
    aggregate_type: str
    event_type: str
    tenant_id: UUID
    occurred_at: datetime
    schema_version: str
    payload_dict: dict[str, Any]
    causation_id: Optional[str] = None
    correlation_id: Optional[str] = None


class OutboxReader(ABC):
    """Outbox 数据访问抽象.

    生产实现: PgOutboxReader (asyncpg + events 表 + event_outbox_cursor 表).
    测试实现: FakeOutboxReader (内存 list + dict).
    """

    @abstractmethod
    async def get_cursor(self, relay_name: str) -> int:
        """获取指定 relay 的 last_sequence. 不存在返回 0."""

    @abstractmethod
    async def fetch_batch(
        self, *, after_sequence: int, limit: int
    ) -> list[PendingEvent]:
        """读取 sequence_num > after_sequence 的事件, 按 sequence 升序."""

    @abstractmethod
    async def update_cursor(
        self,
        *,
        relay_name: str,
        last_sequence: int,
        last_event_id: str,
    ) -> None:
        """原子更新游标."""


class EventRelay:
    """Outbox Relay — PG events 表 → EventBus."""

    DEFAULT_BATCH = 500
    DEFAULT_RELAY_NAME = "ontology_relay_default"

    def __init__(
        self,
        *,
        bus: EventBus,
        reader: OutboxReader,
        schema_registry: dict[str, type[OntologyEvent]],
        batch: int = DEFAULT_BATCH,
        relay_name: str = DEFAULT_RELAY_NAME,
    ) -> None:
        self._bus = bus
        self._reader = reader
        self._schemas = schema_registry
        self._batch = batch
        self._name = relay_name

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    async def run_once(self) -> int:
        """一个 tick: 扫描 -> 转发 -> 更新游标. 返回本次处理的事件数.

        "处理"包括成功发布 + 毒丸跳过; "返回数" 是游标前进的条数.
        """
        last_seq = await self._reader.get_cursor(self._name)
        batch = await self._reader.fetch_batch(
            after_sequence=last_seq, limit=self._batch
        )
        if not batch:
            return 0

        forwarded_count = 0
        last_success: Optional[PendingEvent] = None
        publish_failed = False

        for pending in batch:
            envelope = self._try_build_envelope(pending)
            if envelope is None:
                # 毒丸: 反序列化失败. 跳过但允许游标前进
                last_success = pending
                forwarded_count += 1
                continue

            try:
                await self._bus.publish(envelope)
                forwarded_count += 1
                last_success = pending
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "relay_publish_failed_stopping_batch",
                    relay=self._name,
                    event_id=pending.event_id,
                    sequence_num=pending.sequence_num,
                    error=str(exc),
                )
                publish_failed = True
                break

        # 游标只推进到 last_success
        if last_success is not None:
            await self._reader.update_cursor(
                relay_name=self._name,
                last_sequence=last_success.sequence_num,
                last_event_id=last_success.event_id,
            )

        # 失败路径下调用方通常下一个 tick 再试
        if publish_failed:
            return forwarded_count
        return forwarded_count

    # ------------------------------------------------------------------
    # 内部: PendingEvent -> EventEnvelope
    # ------------------------------------------------------------------

    def _try_build_envelope(
        self, pending: PendingEvent
    ) -> Optional[EventEnvelope]:
        payload_cls = self._schemas.get(pending.event_type)
        if payload_cls is None:
            logger.error(
                "relay_unknown_event_type",
                relay=self._name,
                event_id=pending.event_id,
                event_type=pending.event_type,
            )
            return None
        try:
            payload = payload_cls.model_validate(pending.payload_dict)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "relay_payload_validation_failed",
                relay=self._name,
                event_id=pending.event_id,
                event_type=pending.event_type,
                error=str(exc),
            )
            return None

        return EventEnvelope(
            event_id=pending.event_id,
            aggregate_id=pending.aggregate_id,
            aggregate_type=pending.aggregate_type,
            event_type=pending.event_type,
            tenant_id=pending.tenant_id,
            occurred_at=pending.occurred_at,
            schema_version=pending.schema_version,
            payload=payload,
            causation_id=pending.causation_id,
            correlation_id=pending.correlation_id,
        )
