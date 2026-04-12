"""EventBindingService — 事件→Agent 映射的 CRUD 管理

从 DB 读取 event_agent_bindings 表，支持动态增删改查映射规则。
"""
from __future__ import annotations

from uuid import UUID

import structlog
from sqlalchemy import select, update
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.event_agent_binding import EventAgentBinding

logger = structlog.get_logger(__name__)


class EventBindingService:
    """管理事件→Agent 映射的 CRUD 操作"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_bindings(
        self,
        tenant_id: str,
        *,
        event_type: str | None = None,
        agent_id: str | None = None,
        enabled_only: bool = True,
    ) -> list[EventAgentBinding]:
        """列出映射（支持按 event_type / agent_id 过滤）"""
        stmt = select(EventAgentBinding).where(
            EventAgentBinding.tenant_id == UUID(tenant_id),
            EventAgentBinding.is_deleted == False,  # noqa: E712
        )
        if enabled_only:
            stmt = stmt.where(EventAgentBinding.enabled == True)  # noqa: E712
        if event_type is not None:
            stmt = stmt.where(EventAgentBinding.event_type == event_type)
        if agent_id is not None:
            stmt = stmt.where(EventAgentBinding.agent_id == agent_id)

        stmt = stmt.order_by(EventAgentBinding.priority.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def create_binding(
        self,
        tenant_id: str,
        event_type: str,
        agent_id: str,
        action: str,
        *,
        priority: int = 50,
        condition_json: dict | None = None,
        description: str | None = None,
    ) -> EventAgentBinding:
        """创建新映射"""
        binding = EventAgentBinding(
            tenant_id=UUID(tenant_id),
            event_type=event_type,
            agent_id=agent_id,
            action=action,
            priority=priority,
            condition_json=condition_json,
            description=description,
            source="config",
            enabled=True,
        )
        self.db.add(binding)
        await self.db.flush()
        logger.info(
            "event_binding_created",
            binding_id=str(binding.id),
            event_type=event_type,
            agent_id=agent_id,
            action=action,
        )
        return binding

    async def update_binding(
        self,
        tenant_id: str,
        binding_id: UUID,
        *,
        enabled: bool | None = None,
        priority: int | None = None,
        condition_json: dict | None = None,
    ) -> EventAgentBinding:
        """更新映射（支持 enabled / priority / condition_json）"""
        stmt = select(EventAgentBinding).where(
            EventAgentBinding.id == binding_id,
            EventAgentBinding.tenant_id == UUID(tenant_id),
            EventAgentBinding.is_deleted == False,  # noqa: E712
        )
        result = await self.db.execute(stmt)
        binding = result.scalar_one_or_none()
        if binding is None:
            raise NoResultFound(f"EventAgentBinding {binding_id} not found")

        if enabled is not None:
            binding.enabled = enabled
        if priority is not None:
            binding.priority = priority
        if condition_json is not None:
            binding.condition_json = condition_json

        await self.db.flush()
        logger.info(
            "event_binding_updated",
            binding_id=str(binding_id),
            enabled=enabled,
            priority=priority,
        )
        return binding

    async def delete_binding(
        self,
        tenant_id: str,
        binding_id: UUID,
    ) -> None:
        """删除映射（软删除）"""
        stmt = (
            update(EventAgentBinding)
            .where(
                EventAgentBinding.id == binding_id,
                EventAgentBinding.tenant_id == UUID(tenant_id),
            )
            .values(is_deleted=True)
        )
        result = await self.db.execute(stmt)
        if result.rowcount == 0:
            raise NoResultFound(f"EventAgentBinding {binding_id} not found")
        logger.info("event_binding_deleted", binding_id=str(binding_id))

    async def get_handlers_for_event(
        self,
        tenant_id: str,
        event_type: str,
    ) -> list[dict]:
        """获取某事件类型的所有 handler（按 priority 降序）

        Returns:
            [{"agent_id": "...", "action": "...", "priority": N, "condition": {...}}, ...]
        """
        bindings = await self.list_bindings(
            tenant_id, event_type=event_type, enabled_only=True,
        )
        return [
            {
                "agent_id": b.agent_id,
                "action": b.action,
                "priority": b.priority,
                "condition": b.condition_json,
            }
            for b in bindings
        ]
