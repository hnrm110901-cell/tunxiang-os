"""事件→Agent 映射绑定 API 路由

端点:
  GET    /api/v1/event-bindings/                    — 列出映射
  POST   /api/v1/event-bindings/                    — 创建新映射
  PUT    /api/v1/event-bindings/{binding_id}         — 更新映射
  DELETE /api/v1/event-bindings/{binding_id}         — 删除映射（软删除）
  GET    /api/v1/event-bindings/event-types          — 列出所有已配置的事件类型
  GET    /api/v1/event-bindings/handlers/{event_type} — 获取事件的 handler 列表
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.event_binding_service import EventBindingService

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/event-bindings", tags=["event-bindings"])


# ── Request / Response Models ───────────────────────────────────────────────


class CreateBindingRequest(BaseModel):
    event_type: str = Field(..., max_length=100, description="事件类型")
    agent_id: str = Field(..., max_length=100, description="目标 Agent ID")
    action: str = Field(..., max_length=100, description="要调用的 action")
    priority: int = Field(default=50, ge=0, le=100, description="执行优先级")
    condition_json: dict | None = Field(default=None, description="条件表达式")
    description: str | None = Field(default=None, max_length=500, description="中文描述")


class UpdateBindingRequest(BaseModel):
    enabled: bool | None = Field(default=None, description="是否启用")
    priority: int | None = Field(default=None, ge=0, le=100, description="执行优先级")
    condition_json: dict | None = Field(default=None, description="条件表达式")


class BindingResponse(BaseModel):
    id: str
    event_type: str
    agent_id: str
    action: str
    priority: int
    enabled: bool
    condition_json: dict | None
    description: str | None
    source: str


def _binding_to_dict(b) -> dict:  # noqa: ANN001
    return {
        "id": str(b.id),
        "event_type": b.event_type,
        "agent_id": b.agent_id,
        "action": b.action,
        "priority": b.priority,
        "enabled": b.enabled,
        "condition_json": b.condition_json,
        "description": b.description,
        "source": b.source,
    }


# ── Dependency ──────────────────────────────────────────────────────────────


async def _get_db(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> AsyncSession:
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get("/event-types")
async def list_event_types(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """列出所有已配置的事件类型（distinct event_type）"""
    svc = EventBindingService(db)
    bindings = await svc.list_bindings(x_tenant_id, enabled_only=False)
    event_types = sorted(set(b.event_type for b in bindings))
    return {
        "ok": True,
        "data": {"event_types": event_types, "total": len(event_types)},
    }


@router.get("/handlers/{event_type:path}")
async def get_handlers(
    event_type: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """获取某事件类型的所有 handler（按 priority 降序）"""
    svc = EventBindingService(db)
    handlers = await svc.get_handlers_for_event(x_tenant_id, event_type)
    return {
        "ok": True,
        "data": {"event_type": event_type, "handlers": handlers, "total": len(handlers)},
    }


@router.get("/")
async def list_bindings(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    event_type: str | None = Query(default=None, description="按事件类型过滤"),
    agent_id: str | None = Query(default=None, description="按 Agent ID 过滤"),
    enabled_only: bool = Query(default=True, description="仅显示启用的"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """列出映射（支持过滤）"""
    svc = EventBindingService(db)
    bindings = await svc.list_bindings(
        x_tenant_id,
        event_type=event_type,
        agent_id=agent_id,
        enabled_only=enabled_only,
    )
    return {
        "ok": True,
        "data": {
            "items": [_binding_to_dict(b) for b in bindings],
            "total": len(bindings),
        },
    }


@router.post("/")
async def create_binding(
    body: CreateBindingRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """创建新映射"""
    svc = EventBindingService(db)
    binding = await svc.create_binding(
        x_tenant_id,
        body.event_type,
        body.agent_id,
        body.action,
        priority=body.priority,
        condition_json=body.condition_json,
        description=body.description,
    )
    await db.commit()
    return {"ok": True, "data": _binding_to_dict(binding)}


@router.put("/{binding_id}")
async def update_binding(
    binding_id: UUID,
    body: UpdateBindingRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """更新映射"""
    svc = EventBindingService(db)
    try:
        binding = await svc.update_binding(
            x_tenant_id,
            binding_id,
            enabled=body.enabled,
            priority=body.priority,
            condition_json=body.condition_json,
        )
    except NoResultFound:
        raise HTTPException(status_code=404, detail=f"Binding {binding_id} not found")
    await db.commit()
    return {"ok": True, "data": _binding_to_dict(binding)}


@router.delete("/{binding_id}")
async def delete_binding(
    binding_id: UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """删除映射（软删除）"""
    svc = EventBindingService(db)
    try:
        await svc.delete_binding(x_tenant_id, binding_id)
    except NoResultFound:
        raise HTTPException(status_code=404, detail=f"Binding {binding_id} not found")
    await db.commit()
    return {"ok": True, "data": {"deleted": str(binding_id)}}
