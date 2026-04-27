"""AgentMessageService — Multi-Agent 协调消息总线

提供 Agent 间消息发送、接收、广播、回复、会话追踪等核心操作。
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.agent_message import AgentMessage

logger = structlog.get_logger(__name__)


class AgentMessageService:
    """管理 Agent 间协调消息的 CRUD 操作"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def send_message(
        self,
        tenant_id: str,
        from_agent: str,
        to_agent: str | None,
        message_type: str,
        action: str | None = None,
        payload: dict | None = None,
        *,
        session_id: str | None = None,
        priority: int = 50,
        correlation_id: str | None = None,
        parent_id: str | None = None,
        expires_at: datetime | None = None,
    ) -> AgentMessage:
        """发送一条 Agent 消息"""
        msg = AgentMessage(
            tenant_id=UUID(tenant_id),
            session_id=UUID(session_id) if session_id else None,
            from_agent_id=from_agent,
            to_agent_id=to_agent,
            message_type=message_type,
            action=action,
            payload=payload or {},
            priority=priority,
            status="pending",
            correlation_id=UUID(correlation_id) if correlation_id else None,
            parent_message_id=UUID(parent_id) if parent_id else None,
            expires_at=expires_at,
        )
        self.db.add(msg)
        await self.db.flush()
        logger.info(
            "agent_message_sent",
            message_id=str(msg.id),
            from_agent=from_agent,
            to_agent=to_agent,
            message_type=message_type,
            action=action,
        )
        return msg

    async def get_pending_messages(
        self,
        tenant_id: str,
        agent_id: str,
        limit: int = 10,
    ) -> list[AgentMessage]:
        """获取某 Agent 的待处理消息（按优先级降序、创建时间升序），跳过已过期"""
        now = datetime.now(tz=timezone.utc)
        stmt = (
            select(AgentMessage)
            .where(
                AgentMessage.tenant_id == UUID(tenant_id),
                AgentMessage.is_deleted == False,  # noqa: E712
                AgentMessage.status == "pending",
                # 发给该 agent 或广播消息（排除自己发的广播）
                (AgentMessage.to_agent_id == agent_id)
                | (AgentMessage.to_agent_id.is_(None) & (AgentMessage.from_agent_id != agent_id)),
            )
            .where(
                # 跳过已过期
                (AgentMessage.expires_at.is_(None)) | (AgentMessage.expires_at > now),
            )
            .order_by(AgentMessage.priority.desc(), AgentMessage.created_at.asc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def mark_processed(
        self,
        tenant_id: str,
        message_id: str,
    ) -> AgentMessage:
        """标记消息为已处理"""
        stmt = select(AgentMessage).where(
            AgentMessage.id == UUID(message_id),
            AgentMessage.tenant_id == UUID(tenant_id),
            AgentMessage.is_deleted == False,  # noqa: E712
        )
        result = await self.db.execute(stmt)
        msg = result.scalar_one_or_none()
        if msg is None:
            raise NoResultFound(f"AgentMessage {message_id} not found")

        msg.status = "processed"
        msg.processed_at = datetime.now(tz=timezone.utc)
        await self.db.flush()
        logger.info("agent_message_processed", message_id=str(message_id))
        return msg

    async def broadcast(
        self,
        tenant_id: str,
        from_agent: str,
        message_type: str,
        payload: dict | None = None,
        *,
        session_id: str | None = None,
    ) -> AgentMessage:
        """广播消息（to_agent=None）"""
        return await self.send_message(
            tenant_id=tenant_id,
            from_agent=from_agent,
            to_agent=None,
            message_type=message_type,
            payload=payload,
            session_id=session_id,
        )

    async def get_conversation(
        self,
        tenant_id: str,
        correlation_id: str,
    ) -> list[AgentMessage]:
        """获取会话线程中的所有消息（按创建时间排序）"""
        stmt = (
            select(AgentMessage)
            .where(
                AgentMessage.tenant_id == UUID(tenant_id),
                AgentMessage.correlation_id == UUID(correlation_id),
                AgentMessage.is_deleted == False,  # noqa: E712
            )
            .order_by(AgentMessage.created_at.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def reply(
        self,
        tenant_id: str,
        original_message_id: str,
        from_agent: str,
        payload: dict | None = None,
    ) -> AgentMessage:
        """回复某条消息（自动设置 correlation_id + parent_message_id）"""
        # 查找原始消息
        stmt = select(AgentMessage).where(
            AgentMessage.id == UUID(original_message_id),
            AgentMessage.tenant_id == UUID(tenant_id),
            AgentMessage.is_deleted == False,  # noqa: E712
        )
        result = await self.db.execute(stmt)
        original = result.scalar_one_or_none()
        if original is None:
            raise NoResultFound(f"AgentMessage {original_message_id} not found")

        # correlation_id: 使用原始消息的 correlation_id（若存在），否则用原始消息 ID
        corr_id = original.correlation_id or original.id

        return await self.send_message(
            tenant_id=tenant_id,
            from_agent=from_agent,
            to_agent=original.from_agent_id,
            message_type="response",
            action=original.action,
            payload=payload,
            session_id=str(original.session_id) if original.session_id else None,
            correlation_id=str(corr_id),
            parent_id=original_message_id,
        )
