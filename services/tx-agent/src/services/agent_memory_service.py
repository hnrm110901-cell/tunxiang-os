"""AgentMemoryService — Agent 跨会话记忆的 CRUD + 合并 + 搜索

从 DB 读写 agent_memories 表，支持按类型/键/门店过滤、过期淘汰、
访问计数、ILIKE 模糊搜索（后续接入向量搜索）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import structlog
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.agent_memory import AgentMemory

logger = structlog.get_logger(__name__)


class AgentMemoryService:
    """管理 Agent 跨会话记忆的持久化操作"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def store_memory(
        self,
        tenant_id: str,
        agent_id: str,
        memory_type: str,
        memory_key: str,
        content: dict,
        *,
        confidence: float = 1.0,
        store_id: str | None = None,
        session_id: str | None = None,
        expires_at: datetime | None = None,
    ) -> AgentMemory:
        """存储一条记忆"""
        memory = AgentMemory(
            tenant_id=UUID(tenant_id),
            agent_id=agent_id,
            memory_type=memory_type,
            memory_key=memory_key,
            content=content,
            confidence=confidence,
            store_id=UUID(store_id) if store_id else None,
            session_id=UUID(session_id) if session_id else None,
            expires_at=expires_at,
        )
        self.db.add(memory)
        await self.db.flush()
        logger.info(
            "agent_memory_stored",
            memory_id=str(memory.id),
            agent_id=agent_id,
            memory_type=memory_type,
            memory_key=memory_key,
        )
        return memory

    async def recall_memories(
        self,
        tenant_id: str,
        agent_id: str,
        *,
        memory_type: str | None = None,
        memory_key: str | None = None,
        store_id: str | None = None,
        limit: int = 20,
    ) -> list[AgentMemory]:
        """检索记忆（自动跳过已过期和已删除的，自动递增 access_count）"""
        now = datetime.now(timezone.utc)

        stmt = select(AgentMemory).where(
            AgentMemory.tenant_id == UUID(tenant_id),
            AgentMemory.agent_id == agent_id,
            AgentMemory.is_deleted == False,  # noqa: E712
        )
        # 排除已过期
        stmt = stmt.where(
            (AgentMemory.expires_at.is_(None)) | (AgentMemory.expires_at > now)
        )
        if memory_type is not None:
            stmt = stmt.where(AgentMemory.memory_type == memory_type)
        if memory_key is not None:
            stmt = stmt.where(AgentMemory.memory_key == memory_key)
        if store_id is not None:
            stmt = stmt.where(AgentMemory.store_id == UUID(store_id))

        stmt = stmt.order_by(AgentMemory.updated_at.desc()).limit(limit)
        result = await self.db.execute(stmt)
        memories = list(result.scalars().all())

        # 批量递增 access_count + 更新 last_accessed_at
        if memories:
            memory_ids = [m.id for m in memories]
            await self.db.execute(
                update(AgentMemory)
                .where(AgentMemory.id.in_(memory_ids))
                .values(
                    access_count=AgentMemory.access_count + 1,
                    last_accessed_at=now,
                )
            )

        return memories

    async def search_similar(
        self,
        tenant_id: str,
        query_text: str,
        *,
        agent_id: str | None = None,
        limit: int = 10,
    ) -> list[AgentMemory]:
        """模糊搜索记忆（当前基于 memory_key ILIKE，后续接入向量搜索）"""
        now = datetime.now(timezone.utc)

        stmt = select(AgentMemory).where(
            AgentMemory.tenant_id == UUID(tenant_id),
            AgentMemory.is_deleted == False,  # noqa: E712
            (AgentMemory.expires_at.is_(None)) | (AgentMemory.expires_at > now),
            AgentMemory.memory_key.ilike(
                f"%{query_text.replace('%', '\\%').replace('_', '\\_')}%"
            ),
        )
        if agent_id is not None:
            stmt = stmt.where(AgentMemory.agent_id == agent_id)

        stmt = stmt.order_by(AgentMemory.confidence.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def forget(
        self,
        tenant_id: str,
        memory_id: str,
    ) -> None:
        """软删除一条记忆"""
        stmt = (
            update(AgentMemory)
            .where(
                AgentMemory.id == UUID(memory_id),
                AgentMemory.tenant_id == UUID(tenant_id),
            )
            .values(is_deleted=True)
        )
        result = await self.db.execute(stmt)
        if result.rowcount == 0:
            raise NoResultFound(f"AgentMemory {memory_id} not found")
        logger.info("agent_memory_forgotten", memory_id=memory_id)

    async def consolidate(
        self,
        tenant_id: str,
        agent_id: str,
    ) -> int:
        """合并重复 memory_key 的记忆：保留最高置信度的一条，软删除其余

        Returns:
            合并（删除）的记忆条数
        """
        now = datetime.now(timezone.utc)

        # 找出有重复 memory_key 的组
        dup_stmt = (
            select(
                AgentMemory.memory_type,
                AgentMemory.memory_key,
                func.count().label("cnt"),
            )
            .where(
                AgentMemory.tenant_id == UUID(tenant_id),
                AgentMemory.agent_id == agent_id,
                AgentMemory.is_deleted == False,  # noqa: E712
                (AgentMemory.expires_at.is_(None)) | (AgentMemory.expires_at > now),
            )
            .group_by(AgentMemory.memory_type, AgentMemory.memory_key)
            .having(func.count() > 1)
        )
        dup_result = await self.db.execute(dup_stmt)
        dup_groups = dup_result.all()

        merged_count = 0
        for memory_type, memory_key, _cnt in dup_groups:
            # 获取该组所有记忆，按置信度降序
            group_stmt = (
                select(AgentMemory)
                .where(
                    AgentMemory.tenant_id == UUID(tenant_id),
                    AgentMemory.agent_id == agent_id,
                    AgentMemory.memory_type == memory_type,
                    AgentMemory.memory_key == memory_key,
                    AgentMemory.is_deleted == False,  # noqa: E712
                )
                .order_by(AgentMemory.confidence.desc(), AgentMemory.updated_at.desc())
            )
            group_result = await self.db.execute(group_stmt)
            group_memories = list(group_result.scalars().all())

            # 保留第一条（最高置信度），软删除其余
            keep = group_memories[0]
            to_delete_ids = [m.id for m in group_memories[1:]]
            if to_delete_ids:
                await self.db.execute(
                    update(AgentMemory)
                    .where(AgentMemory.id.in_(to_delete_ids))
                    .values(is_deleted=True)
                )
                # 将被合并条目的 access_count 累加到保留条目
                total_access = sum(m.access_count for m in group_memories[1:])
                keep.access_count += total_access
                merged_count += len(to_delete_ids)

        logger.info(
            "agent_memory_consolidated",
            agent_id=agent_id,
            merged_count=merged_count,
            groups_processed=len(dup_groups),
        )
        return merged_count
