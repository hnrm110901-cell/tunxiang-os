"""Multi-Agent 协调消息 API 路由

端点:
  POST   /api/v1/agent-messages/                        — 发送消息
  GET    /api/v1/agent-messages/pending/{agent_id}      — 获取待处理消息
  POST   /api/v1/agent-messages/{message_id}/process    — 标记为已处理
  POST   /api/v1/agent-messages/broadcast               — 广播消息
  GET    /api/v1/agent-messages/conversation/{corr_id}  — 获取会话线程
  POST   /api/v1/agent-messages/{message_id}/reply      — 回复消息
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.agent_message_service import AgentMessageService

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/agent-messages", tags=["agent-messages"])


# ── Request / Response Models ───────────────────────────────────────────────


class SendMessageRequest(BaseModel):
    from_agent_id: str = Field(..., max_length=100, description="发送方 Agent ID")
    to_agent_id: str | None = Field(default=None, max_length=100, description="接收方 Agent ID（NULL 为广播）")
    message_type: str = Field(..., max_length=50, description="消息类型：request/response/notification/delegation")
    action: str | None = Field(default=None, max_length=100, description="请求执行的动作")
    payload: dict = Field(default_factory=dict, description="消息负载")
    session_id: str | None = Field(default=None, description="可选的会话 ID")
    priority: int = Field(default=50, ge=0, le=100, description="优先级")
    correlation_id: str | None = Field(default=None, description="关联 ID")
    parent_message_id: str | None = Field(default=None, description="父消息 ID")
    expires_at: datetime | None = Field(default=None, description="过期时间")


class BroadcastRequest(BaseModel):
    from_agent_id: str = Field(..., max_length=100, description="发送方 Agent ID")
    message_type: str = Field(..., max_length=50, description="消息类型")
    payload: dict = Field(default_factory=dict, description="消息负载")
    session_id: str | None = Field(default=None, description="可选的会话 ID")


class ReplyRequest(BaseModel):
    from_agent_id: str = Field(..., max_length=100, description="回复方 Agent ID")
    payload: dict = Field(default_factory=dict, description="回复负载")


def _message_to_dict(m) -> dict:  # noqa: ANN001
    return {
        "id": str(m.id),
        "tenant_id": str(m.tenant_id),
        "session_id": str(m.session_id) if m.session_id else None,
        "from_agent_id": m.from_agent_id,
        "to_agent_id": m.to_agent_id,
        "message_type": m.message_type,
        "action": m.action,
        "payload": m.payload,
        "priority": m.priority,
        "status": m.status,
        "correlation_id": str(m.correlation_id) if m.correlation_id else None,
        "parent_message_id": str(m.parent_message_id) if m.parent_message_id else None,
        "processed_at": m.processed_at.isoformat() if m.processed_at else None,
        "expires_at": m.expires_at.isoformat() if m.expires_at else None,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


# ── Dependency ──────────────────────────────────────────────────────────────


async def _get_db(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> AsyncSession:
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ── Routes ──────────────────────────────────────────────────────────────────


@router.post("/")
async def send_message(
    body: SendMessageRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """发送 Agent 消息"""
    svc = AgentMessageService(db)
    msg = await svc.send_message(
        tenant_id=x_tenant_id,
        from_agent=body.from_agent_id,
        to_agent=body.to_agent_id,
        message_type=body.message_type,
        action=body.action,
        payload=body.payload,
        session_id=body.session_id,
        priority=body.priority,
        correlation_id=body.correlation_id,
        parent_id=body.parent_message_id,
        expires_at=body.expires_at,
    )
    await db.commit()
    return {"ok": True, "data": _message_to_dict(msg)}


@router.get("/pending/{agent_id}")
async def get_pending_messages(
    agent_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    limit: int = Query(default=10, ge=1, le=100, description="最大返回条数"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """获取某 Agent 的待处理消息"""
    svc = AgentMessageService(db)
    messages = await svc.get_pending_messages(x_tenant_id, agent_id, limit=limit)
    return {
        "ok": True,
        "data": {
            "items": [_message_to_dict(m) for m in messages],
            "total": len(messages),
        },
    }


@router.post("/{message_id}/process")
async def mark_processed(
    message_id: UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """标记消息为已处理"""
    svc = AgentMessageService(db)
    try:
        msg = await svc.mark_processed(x_tenant_id, str(message_id))
    except NoResultFound:
        raise HTTPException(status_code=404, detail=f"Message {message_id} not found")
    await db.commit()
    return {"ok": True, "data": _message_to_dict(msg)}


@router.post("/broadcast")
async def broadcast(
    body: BroadcastRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """广播消息给所有 Agent"""
    svc = AgentMessageService(db)
    msg = await svc.broadcast(
        tenant_id=x_tenant_id,
        from_agent=body.from_agent_id,
        message_type=body.message_type,
        payload=body.payload,
        session_id=body.session_id,
    )
    await db.commit()
    return {"ok": True, "data": _message_to_dict(msg)}


@router.get("/conversation/{correlation_id}")
async def get_conversation(
    correlation_id: UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """获取会话线程中的所有消息"""
    svc = AgentMessageService(db)
    messages = await svc.get_conversation(x_tenant_id, str(correlation_id))
    return {
        "ok": True,
        "data": {
            "items": [_message_to_dict(m) for m in messages],
            "total": len(messages),
        },
    }


@router.post("/{message_id}/reply")
async def reply_message(
    message_id: UUID,
    body: ReplyRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """回复某条消息"""
    svc = AgentMessageService(db)
    try:
        msg = await svc.reply(
            tenant_id=x_tenant_id,
            original_message_id=str(message_id),
            from_agent=body.from_agent_id,
            payload=body.payload,
        )
    except NoResultFound:
        raise HTTPException(status_code=404, detail=f"Message {message_id} not found")
    await db.commit()
    return {"ok": True, "data": _message_to_dict(msg)}
