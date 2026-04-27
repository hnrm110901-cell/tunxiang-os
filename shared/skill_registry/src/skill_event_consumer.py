"""
SkillRouter EventBus Consumer

在现有 Redis Stream 事件总线上注册新的 Consumer Group "skill-router"，
监听所有业务域事件，按 SKILL.yaml triggers 路由到对应 Skill handler。

与现有 DomainEventConsumer 并行，互不影响。
"""

import asyncio
import json
import logging
from typing import Awaitable, Callable

import redis.asyncio as redis

logger = logging.getLogger(__name__)

# 屯象OS 8个业务域 Redis Stream
SKILL_STREAMS = [
    "trade:events",
    "supply:events",
    "finance:events",
    "org:events",
    "menu:events",
    "member:events",
    "ops:events",
    "agent:events",
]

CONSUMER_GROUP = "skill-router"
CONSUMER_NAME = "skill-router-worker-1"

SkillHandler = Callable[[str, dict, dict], Awaitable[None]]
# skill_name, event_type, payload


class SkillEventConsumer:
    """
    Redis Stream消费者，将事件路由到注册的Skill handlers。

    用法：
        consumer = SkillEventConsumer(redis_url="redis://localhost:6379")
        consumer.register_handler("order-core", my_order_handler)
        await consumer.start()
    """

    def __init__(self, redis_url: str, registry=None):
        self.redis_url = redis_url
        self.registry = registry  # SkillRegistry instance
        self._handlers: dict[str, SkillHandler] = {}  # skill_name → handler
        self._running = False

    async def ensure_groups(self, r: redis.Redis):
        """确保所有Stream的Consumer Group存在"""
        for stream in SKILL_STREAMS:
            try:
                await r.xgroup_create(stream, CONSUMER_GROUP, id="$", mkstream=True)
                logger.info(f"Created consumer group {CONSUMER_GROUP} on {stream}")
            except redis.ResponseError as e:
                if "BUSYGROUP" in str(e):
                    pass  # 已存在，正常
                else:
                    logger.warning(f"Error creating group on {stream}: {e}")

    def register_handler(self, skill_name: str, handler: SkillHandler):
        """注册Skill事件处理器"""
        self._handlers[skill_name] = handler

    async def start(self):
        """启动消费循环（后台任务）"""
        self._running = True
        r = redis.from_url(self.redis_url, decode_responses=True)
        await self.ensure_groups(r)

        logger.info(f"SkillEventConsumer started, listening on {len(SKILL_STREAMS)} streams")

        while self._running:
            try:
                results = await r.xreadgroup(
                    groupname=CONSUMER_GROUP,
                    consumername=CONSUMER_NAME,
                    streams=dict.fromkeys(SKILL_STREAMS, ">"),
                    count=10,
                    block=1000,  # 1秒超时
                )

                if not results:
                    continue

                for stream_name, messages in results:
                    for msg_id, msg_data in messages:
                        await self._dispatch(stream_name, msg_id, msg_data, r)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"SkillEventConsumer error: {e}", exc_info=True)
                await asyncio.sleep(1)

        await r.aclose()

    async def _dispatch(self, stream: str, msg_id: str, msg_data: dict, r: redis.Redis):
        """将消息路由到对应Skill"""
        try:
            event_type = msg_data.get("event_type", "")
            payload = json.loads(msg_data.get("payload", "{}"))

            # 如果有SkillRegistry，用它来路由
            if self.registry:
                matches = self.registry.find_by_event_type(event_type)
                for skill_manifest, trigger in matches:
                    skill_name = skill_manifest.meta.name
                    if skill_name in self._handlers:
                        try:
                            await self._handlers[skill_name](skill_name, event_type, payload)
                        except Exception as e:
                            logger.error(f"Skill handler {skill_name} error for {event_type}: {e}")

            # ACK消息
            await r.xack(stream, CONSUMER_GROUP, msg_id)

        except Exception as e:
            logger.error(f"Dispatch error for msg {msg_id}: {e}")

    async def stop(self):
        self._running = False
