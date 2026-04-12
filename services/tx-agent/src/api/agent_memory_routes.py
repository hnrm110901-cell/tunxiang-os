"""Agent Memory 跨会话记忆 API 路由

端点:
  POST   /api/v1/agent-memory/              — 存储记忆
  GET    /api/v1/agent-memory/              — 检索记忆
  GET    /api/v1/agent-memory/search        — 模糊搜索
  DELETE /api/v1/agent-memory/{memory_id}   — 软删除
  POST   /api/v1/agent-memory/consolidate   — 合并重复记忆
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

from ..services.agent_memory_service import AgentMemoryService

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/agent-memory", tags=["agent-memory"])


# ── Request / Response Models ───────────────────────────────────────────────


class StoreMemoryRequest(BaseModel):
    agent_id: str = Field(..., max_length=100, description="Agent ID")
    memory_type: str = Field(..., max_length=50, description="记忆类型：finding/insight/preference/learned_rule")
    memory_key: str = Field(..., max_length=200, description="可搜索的记忆键")
    content: dict = Field(..., description="记忆内容")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="置信度")
    store_id: str | None = Field(default=None, description="门店 ID（可选）")
    session_id: str | None = Field(default=None, description="会话 ID（可选）")
    expires_at: datetime | None = Field(default=None, description="过期时间（可选）")


class ConsolidateRequest(BaseModel):
    agent_id: str = Field(..., max_length=100, description="Agent ID")


class MemoryResponse(BaseModel):
    id: str
    agent_id: str
    memory_type: str
    memory_key: str
    content: dict
    confidence: float
    store_id: str | None
    session_id: str | None
    embedding_id: str | None
    access_count: int
    last_accessed_at: str | None
    expires_at: str | None
    created_at: str
    updated_at: str


def _memory_to_dict(m) -> dict:  # noqa: ANN001
    return {
        "id": str(m.id),
        "agent_id": m.agent_id,
        "memory_type": m.memory_type,
        "memory_key": m.memory_key,
        "content": m.content,
        "confidence": m.confidence,
        "store_id": str(m.store_id) if m.store_id else None,
        "session_id": str(m.session_id) if m.session_id else None,
        "embedding_id": m.embedding_id,
        "access_count": m.access_count,
        "last_accessed_at": m.last_accessed_at.isoformat() if m.last_accessed_at else None,
        "expires_at": m.expires_at.isoformat() if m.expires_at else None,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


# ── Dependency ──────────────────────────────────────────────────────────────


async def _get_db(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> AsyncSession:
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get("/search")
async def search_memories(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    agent_id: str | None = Query(default=None, description="按 Agent ID 过滤"),
    limit: int = Query(default=10, ge=1, le=100, description="返回条数"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """模糊搜索记忆（基于 memory_key ILIKE，后续接入向量搜索）"""
    svc = AgentMemoryService(db)
    memories = await svc.search_similar(
        x_tenant_id,
        q,
        agent_id=agent_id,
        limit=limit,
    )
    return {
        "ok": True,
        "data": {
            "items": [_memory_to_dict(m) for m in memories],
            "total": len(memories),
        },
    }


@router.get("/")
async def recall_memories(
    agent_id: str = Query(..., description="Agent ID"),
    memory_type: str | None = Query(default=None, description="按记忆类型过滤"),
    memory_key: str | None = Query(default=None, description="按记忆键过滤"),
    store_id: str | None = Query(default=None, description="按门店过滤"),
    limit: int = Query(default=20, ge=1, le=100, description="返回条数"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """检索记忆（自动跳过已过期，自动递增访问计数）"""
    svc = AgentMemoryService(db)
    memories = await svc.recall_memories(
        x_tenant_id,
        agent_id,
        memory_type=memory_type,
        memory_key=memory_key,
        store_id=store_id,
        limit=limit,
    )
    await db.commit()
    return {
        "ok": True,
        "data": {
            "items": [_memory_to_dict(m) for m in memories],
            "total": len(memories),
        },
    }


@router.post("/")
async def store_memory(
    body: StoreMemoryRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """存储一条记忆"""
    svc = AgentMemoryService(db)
    memory = await svc.store_memory(
        x_tenant_id,
        body.agent_id,
        body.memory_type,
        body.memory_key,
        body.content,
        confidence=body.confidence,
        store_id=body.store_id,
        session_id=body.session_id,
        expires_at=body.expires_at,
    )
    await db.commit()
    return {"ok": True, "data": _memory_to_dict(memory)}


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """软删除一条记忆"""
    svc = AgentMemoryService(db)
    try:
        await svc.forget(x_tenant_id, str(memory_id))
    except NoResultFound:
        raise HTTPException(status_code=404, detail=f"Memory {memory_id} not found")
    await db.commit()
    return {"ok": True, "data": {"deleted": str(memory_id)}}


@router.post("/consolidate")
async def consolidate_memories(
    body: ConsolidateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """合并重复记忆（保留最高置信度，软删除其余）"""
    svc = AgentMemoryService(db)
    merged_count = await svc.consolidate(x_tenant_id, body.agent_id)
    await db.commit()
    return {
        "ok": True,
        "data": {"agent_id": body.agent_id, "merged_count": merged_count},
    }
