"""MemberEventPublisher — 向 Redis Stream 发布会员行为事件

使用方式（在业务代码中，不阻塞主流程）：
    import asyncio
    asyncio.create_task(MemberEventPublisher.publish(
        MemberEventType.STORED_VALUE_RECHARGED,
        tenant_id=tenant_id,
        customer_id=card.customer_id,
        event_data={"amount_fen": 10000, "card_id": str(card.id)},
        source_service="tx-member",
    ))

设计要点：
- 单例 Redis 连接（类变量），避免每次调用都建立连接
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
STREAM_KEY: str = "member_events"
MAX_STREAM_LENGTH: int = 100_000


class MemberEventPublisher:
    """Redis Stream 事件发布器（类方法接口，单例连接）"""

    # 延迟初始化，避免模块导入时就建立连接
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
    async def publish(
        cls,
        event_type: "MemberEventType",  # type: ignore[name-defined]
        tenant_id: UUID,
        customer_id: UUID,
        event_data: dict,
        source_service: str = "unknown",
    ) -> Optional[str]:
        """发布事件到 Redis Stream。

        Args:
            event_type:     事件类型（MemberEventType）
            tenant_id:      租户 UUID
            customer_id:    客户 UUID
            event_data:     事件具体数据（dict，会被 JSON 序列化）
            source_service: 来源服务名

        Returns:
            Redis Stream entry ID（如 "1699000000000-0"），失败时返回 None。

        注意：
            此方法在 Redis 不可用时会降级（不抛异常），
            调用方用 asyncio.create_task() 包裹，确保不阻塞主业务。
        """
        try:
            redis = await cls.get_redis()

            fields: dict[str, str] = {
                "event_id": str(uuid4()),
                "event_type": event_type.value
                if hasattr(event_type, "value")
                else str(event_type),
                "tenant_id": str(tenant_id),
                "customer_id": str(customer_id),
                "event_data": json.dumps(event_data, ensure_ascii=False),
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "source_service": source_service,
            }

            entry_id: str = await redis.xadd(
                STREAM_KEY,
                fields,
                maxlen=MAX_STREAM_LENGTH,
                approximate=True,
            )

            logger.info(
                "member_event_published",
                event_type=fields["event_type"],
                tenant_id=str(tenant_id),
                customer_id=str(customer_id),
                entry_id=entry_id,
                source_service=source_service,
            )
            return entry_id

        except OSError as exc:
            # Redis 连接失败（网络问题）— 降级，不影响主业务
            logger.warning(
                "member_event_publish_failed_os",
                event_type=str(event_type),
                tenant_id=str(tenant_id),
                customer_id=str(customer_id),
                error=str(exc),
            )
            cls._redis = None  # 重置连接，下次重试
            return None
        except RuntimeError as exc:
            # Redis 协议层异常（如连接池耗尽）
            logger.warning(
                "member_event_publish_failed_runtime",
                event_type=str(event_type),
                tenant_id=str(tenant_id),
                customer_id=str(customer_id),
                error=str(exc),
            )
            return None

    @classmethod
    async def close(cls) -> None:
        """关闭 Redis 连接（服务关闭时调用）"""
        if cls._redis is not None:
            await cls._redis.aclose()
            cls._redis = None
            logger.info("member_event_publisher_closed")
