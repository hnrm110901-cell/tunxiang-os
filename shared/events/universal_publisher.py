"""UniversalPublisher — 向 Redis Stream 发布全域业务事件

使用方式（在业务代码中，不阻塞主流程）：
    import asyncio
    asyncio.create_task(UniversalPublisher.publish(
        TradeEventType.ORDER_PAID,
        tenant_id=tenant_id,
        store_id=store_id,
        entity_id=order_id,
        event_data={"total_fen": 8800, "channel": "dine_in"},
        source_service="tx-trade",
    ))

设计要点：
- 单例 Redis 连接（类变量），避免每次调用都建立连接
- 根据 event_type 字符串第一段自动路由到对应 Redis Stream
- Redis 不可用时降级（记录日志，不抛异常，不影响主业务）
- Stream MAXLEN ~ 100_000，自动修剪旧事件
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

import structlog

logger = structlog.get_logger(__name__)

REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
MAX_STREAM_LENGTH: int = 100_000

STREAM_KEYS: dict[str, str] = {
    "trade": "trade_events",
    "supply": "supply_events",
    "finance": "finance_events",
    "org": "org_events",
    "menu": "menu_events",
    "ops": "ops_events",
}


class UniversalPublisher:
    """通用 Redis Stream 事件发布器（类方法接口，单例连接）

    支持所有业务域的事件类型，根据 event_type 字符串第一段自动路由。
    """

    _redis: "Optional[aioredis.Redis]" = None  # type: ignore[name-defined]

    @classmethod
    async def get_redis(cls) -> "aioredis.Redis":  # type: ignore[name-defined]
        """获取（或创建）Redis 连接单例"""
        import redis.asyncio as aioredis

        if cls._redis is None:
            cls._redis = await aioredis.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
        return cls._redis

    @classmethod
    def _resolve_stream_key(cls, event_type_value: str) -> Optional[str]:
        """根据事件类型字符串第一段解析目标 Stream key"""
        domain = event_type_value.split(".")[0]
        return STREAM_KEYS.get(domain)

    @classmethod
    async def publish(
        cls,
        event_type: object,
        tenant_id: UUID,
        store_id: Optional[UUID],
        entity_id: Optional[UUID],
        event_data: dict,
        source_service: str = "unknown",
        extra_fields: Optional[dict] = None,
    ) -> Optional[str]:
        """发布事件到对应域的 Redis Stream。

        Args:
            event_type:     任意域的 EventType 枚举值
            tenant_id:      租户 UUID
            store_id:       门店 UUID（品牌级事件可为 None）
            entity_id:      主体实体 UUID（可为 None）
            event_data:     事件具体数据（dict，会被 JSON 序列化）
            source_service: 来源服务名
            extra_fields:   各域 Event 特有字段（如 org 域的 employee_id）

        Returns:
            Redis Stream entry ID（如 "1699000000000-0"），失败时返回 None。

        注意：
            此方法在 Redis 不可用时会降级（不抛异常），
            调用方用 asyncio.create_task() 包裹，确保不阻塞主业务。
        """
        event_type_value: str = (
            event_type.value  # type: ignore[union-attr]
            if hasattr(event_type, "value")
            else str(event_type)
        )

        stream_key = cls._resolve_stream_key(event_type_value)
        if stream_key is None:
            logger.warning(
                "universal_publisher_unknown_domain",
                event_type=event_type_value,
            )
            return None

        try:
            redis = await cls.get_redis()

            fields: dict[str, str] = {
                "event_id": str(uuid4()),
                "event_type": event_type_value,
                "tenant_id": str(tenant_id),
                "store_id": str(store_id) if store_id is not None else "",
                "entity_id": str(entity_id) if entity_id is not None else "",
                "event_data": json.dumps(event_data, ensure_ascii=False),
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "source_service": source_service,
            }

            if extra_fields:
                for key, value in extra_fields.items():
                    fields[key] = str(value) if value is not None else ""

            entry_id: str = await redis.xadd(
                stream_key,
                fields,
                maxlen=MAX_STREAM_LENGTH,
                approximate=True,
            )

            logger.info(
                "universal_event_published",
                event_type=event_type_value,
                stream_key=stream_key,
                tenant_id=str(tenant_id),
                store_id=str(store_id),
                entry_id=entry_id,
                source_service=source_service,
            )
            return entry_id

        except OSError as exc:
            logger.warning(
                "universal_event_publish_failed_os",
                event_type=event_type_value,
                stream_key=stream_key,
                tenant_id=str(tenant_id),
                error=str(exc),
            )
            cls._redis = None
            return None
        except RuntimeError as exc:
            logger.warning(
                "universal_event_publish_failed_runtime",
                event_type=event_type_value,
                stream_key=stream_key,
                tenant_id=str(tenant_id),
                error=str(exc),
            )
            return None

    @classmethod
    async def close(cls) -> None:
        """关闭 Redis 连接（服务关闭时调用）"""
        if cls._redis is not None:
            await cls._redis.aclose()
            cls._redis = None
            logger.info("universal_publisher_closed")
