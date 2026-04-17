"""
Agent Memory Bus - Agent共享记忆总线

Redis Streams-based pub/sub so agents can share findings across a store
without direct coupling. Each finding is a lightweight JSON entry on a
per-store stream.

Stream key: agent:stream:{store_id}
Entry fields: agent, action, summary, confidence, data (JSON), ts

Usage:
    from src.services.agent_memory_bus import agent_memory_bus

    # publish a finding
    await agent_memory_bus.publish(
        store_id="store_001",
        agent_id="inventory",
        action="low_stock_alert",
        summary="辣椒库存不足，预计4小时内耗尽",
        confidence=0.92,
        data={"item": "chili", "remaining": 5},
    )

    # read recent findings from all agents for this store
    findings = await agent_memory_bus.subscribe(store_id="store_001", last_n=20)
"""

import json
import os
from typing import Any, Dict, List, Optional

import structlog

from ..core.clock import now_utc
from ..core.config import settings

logger = structlog.get_logger()

# Max entries kept per store stream (older entries auto-trimmed)
STREAM_MAX_LEN = int(os.getenv("AGENT_MEMORY_STREAM_MAX_LEN", "200"))
# Default TTL for the stream key (seconds) — 24 hours
STREAM_TTL = int(os.getenv("AGENT_MEMORY_STREAM_TTL", "86400"))


class AgentMemoryBus:
    """Redis Streams-based shared memory bus for agents."""

    def __init__(self):
        self._redis = None

    async def _get_redis(self):
        if self._redis is None:
            import redis.asyncio as aioredis

            self._redis = await aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    def _stream_key(self, store_id: str) -> str:
        return f"agent:stream:{store_id}"

    async def publish(
        self,
        store_id: str,
        agent_id: str,
        action: str,
        summary: str,
        confidence: float = 0.0,
        data: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Publish a finding to the store's agent stream.

        Returns the Redis stream entry ID, or None on failure.
        """
        try:
            r = await self._get_redis()
            key = self._stream_key(store_id)

            entry = {
                "agent": agent_id,
                "action": action,
                "summary": summary,
                "confidence": str(round(confidence, 4)),
                "data": json.dumps(data or {}, ensure_ascii=False),
                "ts": now_utc().isoformat(),
            }

            entry_id = await r.xadd(key, entry, maxlen=STREAM_MAX_LEN, approximate=True)
            # Refresh TTL so active stores keep their stream alive
            await r.expire(key, STREAM_TTL)

            logger.info(
                "agent_memory_published",
                store_id=store_id,
                agent_id=agent_id,
                action=action,
                entry_id=entry_id,
            )
            return entry_id

        except Exception as e:
            logger.warning("agent_memory_publish_failed", store_id=store_id, error=str(e))
            return None

    async def subscribe(
        self,
        store_id: str,
        last_n: int = 20,
        agent_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Read the last N findings from the store's agent stream.

        Args:
            store_id:     Store to read from.
            last_n:       How many recent entries to return (newest first).
            agent_filter: If set, only return findings from this agent.

        Returns:
            List of finding dicts, newest first.
        """
        try:
            r = await self._get_redis()
            key = self._stream_key(store_id)

            # xrevrange returns entries newest-first
            raw = await r.xrevrange(key, count=last_n * 3 if agent_filter else last_n)

            findings = []
            for entry_id, fields in raw:
                if agent_filter and fields.get("agent") != agent_filter:
                    continue
                try:
                    finding = {
                        "entry_id": entry_id,
                        "agent": fields.get("agent"),
                        "action": fields.get("action"),
                        "summary": fields.get("summary"),
                        "confidence": float(fields.get("confidence", 0)),
                        "data": json.loads(fields.get("data", "{}")),
                        "ts": fields.get("ts"),
                    }
                    findings.append(finding)
                    if len(findings) >= last_n:
                        break
                except Exception:
                    continue

            return findings

        except Exception as e:
            logger.warning("agent_memory_subscribe_failed", store_id=store_id, error=str(e))
            return []

    async def get_peer_context(
        self,
        store_id: str,
        requesting_agent: str,
        last_n: int = 10,
    ) -> str:
        """
        Return a formatted string of recent peer findings for LLM context injection.

        Excludes findings from the requesting agent itself.
        """
        findings = await self.subscribe(store_id, last_n=last_n * 2)
        peer_findings = [f for f in findings if f["agent"] != requesting_agent][:last_n]

        if not peer_findings:
            return ""

        lines = ["[同店其他Agent最新发现]"]
        for f in peer_findings:
            conf = f"{f['confidence']:.0%}" if f["confidence"] else ""
            lines.append(f"- [{f['agent']}] {f['action']}: {f['summary']}{' (' + conf + ')' if conf else ''}")

        return "\n".join(lines)

    async def stream_length(self, store_id: str) -> int:
        """Return current number of entries in the store's stream."""
        try:
            r = await self._get_redis()
            return await r.xlen(self._stream_key(store_id))
        except Exception:
            return 0

    # ─────────────────────────────────────────────────────────────────────
    # D6 Should-Fix P1: 三级持久化记忆
    #   hot(Redis, TTL 1h) → warm(PostgreSQL, 7天) → cold(归档，永久)
    # ─────────────────────────────────────────────────────────────────────

    HOT_TTL_SEC = 3600  # hot 层 TTL 1 小时
    WARM_DAYS = 7  # warm 层保留 7 天

    def _mem_key(self, agent_id: str, session_id: str, key: str) -> str:
        """hot 层 Redis key 规范：agent:mem:{agent_id}:{session_id}:{key}"""
        return f"agent:mem:{agent_id}:{session_id}:{key}"

    async def save_memory(
        self,
        agent_id: str,
        session_id: str,
        key: str,
        value: Any,
        level: str = "hot",
    ) -> bool:
        """
        保存记忆到指定层级

        Args:
            level: 'hot' (Redis TTL 1h) | 'warm' (PG 7d) | 'cold' (PG 永久)
        """
        try:
            if level == "hot":
                r = await self._get_redis()
                redis_key = self._mem_key(agent_id, session_id, key)
                await r.set(redis_key, json.dumps(value, ensure_ascii=False), ex=self.HOT_TTL_SEC)
                return True

            # warm / cold 写 PG
            from datetime import timedelta

            from sqlalchemy import select
            from sqlalchemy.dialects.postgresql import insert

            from ..core.database import async_session_maker
            from ..models.agent_memory import AgentMemory

            expires_at = None
            if level == "warm":
                expires_at = now_utc() + timedelta(days=self.WARM_DAYS)

            async with async_session_maker() as session:
                # upsert on (agent_id, session_id, key)
                stmt = insert(AgentMemory).values(
                    agent_id=agent_id,
                    session_id=session_id,
                    key=key,
                    value_json=value,
                    level=level,
                    expires_at=expires_at,
                )
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_agent_memory_key",
                    set_={
                        "value_json": value,
                        "level": level,
                        "expires_at": expires_at,
                        "updated_at": now_utc(),
                    },
                )
                await session.execute(stmt)
                await session.commit()
            return True

        except Exception as e:
            logger.warning("agent_memory_save_failed", agent_id=agent_id, key=key, error=str(e))
            return False

    async def load_memory(
        self,
        agent_id: str,
        session_id: str,
        key: str,
    ) -> Optional[Any]:
        """
        读取记忆。hot 未命中自动 promote warm→hot
        """
        # 1) hot
        try:
            r = await self._get_redis()
            raw = await r.get(self._mem_key(agent_id, session_id, key))
            if raw:
                return json.loads(raw)
        except Exception as e:
            logger.debug("agent_memory_hot_miss", error=str(e))

        # 2) warm / cold — 读 PG
        try:
            from sqlalchemy import select

            from ..core.database import async_session_maker
            from ..models.agent_memory import AgentMemory

            async with async_session_maker() as session:
                result = await session.execute(
                    select(AgentMemory).where(
                        AgentMemory.agent_id == agent_id,
                        AgentMemory.session_id == session_id,
                        AgentMemory.key == key,
                    )
                )
                row = result.scalar_one_or_none()
                if row is None:
                    return None
                # promote warm→hot（cold 也 promote，让高频访问自动暖）
                try:
                    r = await self._get_redis()
                    await r.set(
                        self._mem_key(agent_id, session_id, key),
                        json.dumps(row.value_json, ensure_ascii=False),
                        ex=self.HOT_TTL_SEC,
                    )
                except Exception:
                    pass
                return row.value_json

        except Exception as e:
            logger.warning("agent_memory_load_failed", agent_id=agent_id, key=key, error=str(e))
            return None

    async def evict_expired(self) -> int:
        """
        降级 warm 层已过期记忆到 cold（level='cold', expires_at=NULL）
        返回降级条数。
        """
        try:
            from sqlalchemy import update

            from ..core.database import async_session_maker
            from ..models.agent_memory import AgentMemory

            async with async_session_maker() as session:
                result = await session.execute(
                    update(AgentMemory)
                    .where(
                        AgentMemory.level == "warm",
                        AgentMemory.expires_at.isnot(None),
                        AgentMemory.expires_at < now_utc(),
                    )
                    .values(level="cold", expires_at=None)
                )
                await session.commit()
                return result.rowcount or 0
        except Exception as e:
            logger.warning("agent_memory_evict_failed", error=str(e))
            return 0


# Singleton
agent_memory_bus = AgentMemoryBus()
