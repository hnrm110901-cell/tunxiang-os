"""Session Runtime API — Session 运行实例管理路由

prefix: /api/v1/sessions

端点列表：
  POST   /                                  — 创建 Session
  GET    /                                  — 列出 Sessions（分页+过滤）
  GET    /{session_id}                      — 获取 Session 详情
  POST   /{session_id}/start               — 启动 Session
  POST   /{session_id}/pause               — 暂停 Session
  POST   /{session_id}/cancel              — 取消 Session
  GET    /{session_id}/checkpoints         — 获取 Session 的所有 checkpoint
  POST   /checkpoints/{checkpoint_id}/resolve — 恢复 Session（解决 checkpoint）
  GET    /{session_id}/timeline            — 获取 Session 事件时间线
  GET    /cost/summary                     — 成本汇总
  GET    /cost/trend                       — 每日成本趋势
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.session_cost_service import SessionCostService
from ..services.session_runtime_service import (
    SessionNotFoundError,
    SessionRuntimeService,
    SessionStateError,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/sessions", tags=["session-runtime"])


# ─────────────────────────────────────────────────────────────────────────────
# 依赖
# ─────────────────────────────────────────────────────────────────────────────

async def _get_db(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> AsyncSession:
    """依赖：从 X-Tenant-ID header 提取租户 ID，返回带 RLS 隔离的 DB session。"""
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ─────────────────────────────────────────────────────────────────────────────
# Request / Response Schemas
# ─────────────────────────────────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    agent_template_name: str | None = None
    store_id: UUID | None = None
    trigger_type: str = Field(..., description="触发类型: event/manual/scheduled/api")
    trigger_data: dict | None = None


class PauseSessionRequest(BaseModel):
    step_id: str
    agent_id: str | None = None
    reason: str = Field(..., description="暂停原因: pause/error/human_review/risk_approval")
    reason_detail: str | None = None
    checkpoint_data: dict | None = None
    pending_action: dict | None = None


class ResolveCheckpointRequest(BaseModel):
    session_id: UUID
    resolution: str = Field(..., description="解决结果: approved/rejected/skipped")
    resolved_by: str
    comment: str | None = None


class CompleteSessionRequest(BaseModel):
    result_json: dict | None = None
    total_tokens: int = 0
    total_cost_fen: int = 0


class FailSessionRequest(BaseModel):
    error_message: str


# ─────────────────────────────────────────────────────────────────────────────
# 序列化辅助
# ─────────────────────────────────────────────────────────────────────────────

def _serialize_session(s: Any) -> dict:
    """将 SessionRun ORM 实例序列化为 dict。"""
    return {
        "id": str(s.id),
        "tenant_id": str(s.tenant_id),
        "session_id": s.session_id,
        "agent_template_name": s.agent_template_name,
        "store_id": str(s.store_id) if s.store_id else None,
        "trigger_type": s.trigger_type,
        "trigger_data": s.trigger_data,
        "status": s.status,
        "plan_id": s.plan_id,
        "result_json": s.result_json,
        "error_message": s.error_message,
        "total_steps": s.total_steps,
        "completed_steps": s.completed_steps,
        "failed_steps": s.failed_steps,
        "total_tokens": s.total_tokens,
        "total_cost_fen": s.total_cost_fen,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "finished_at": s.finished_at.isoformat() if s.finished_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _serialize_event(e: Any) -> dict:
    """将 SessionEvent ORM 实例序列化为 dict。"""
    return {
        "id": str(e.id),
        "session_id": str(e.session_id),
        "sequence_no": e.sequence_no,
        "event_type": e.event_type,
        "step_id": e.step_id,
        "agent_id": e.agent_id,
        "action": e.action,
        "input_json": e.input_json,
        "output_json": e.output_json,
        "reasoning": e.reasoning,
        "tokens_used": e.tokens_used,
        "duration_ms": e.duration_ms,
        "inference_layer": e.inference_layer,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


def _serialize_checkpoint(c: Any) -> dict:
    """将 SessionCheckpoint ORM 实例序列化为 dict。"""
    return {
        "id": str(c.id),
        "session_id": str(c.session_id),
        "step_id": c.step_id,
        "agent_id": c.agent_id,
        "reason": c.reason,
        "reason_detail": c.reason_detail,
        "checkpoint_data": c.checkpoint_data,
        "pending_action": c.pending_action,
        "resolution": c.resolution,
        "resolved_by": c.resolved_by,
        "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
        "resolved_comment": c.resolved_comment,
        "resumed_at": c.resumed_at.isoformat() if c.resumed_at else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 成本路由（放在参数化路由之前，避免被 /{session_id} 拦截）
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/cost/summary")
async def get_cost_summary(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
    store_id: UUID | None = Query(default=None),
    agent_template_name: str | None = Query(default=None),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
) -> dict[str, Any]:
    """按维度聚合成本统计。"""
    svc = SessionCostService(db)
    summary = await svc.get_cost_summary(
        x_tenant_id,
        store_id=store_id,
        agent_template_name=agent_template_name,
        start_date=start_date,
        end_date=end_date,
    )
    return {"ok": True, "data": summary}


@router.get("/cost/trend")
async def get_daily_cost_trend(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
    days: int = Query(default=30, ge=1, le=365),
    store_id: UUID | None = Query(default=None),
) -> dict[str, Any]:
    """按天聚合成本趋势。"""
    svc = SessionCostService(db)
    trend = await svc.get_daily_cost_trend(
        x_tenant_id,
        days=days,
        store_id=store_id,
    )
    return {"ok": True, "data": trend}


# ─────────────────────────────────────────────────────────────────────────────
# Checkpoint 路由（放在参数化路由之前）
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/checkpoints/{checkpoint_id}/resolve")
async def resolve_checkpoint(
    checkpoint_id: UUID,
    req: ResolveCheckpointRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """解决 checkpoint 并恢复 Session（paused → running）。"""
    svc = SessionRuntimeService(db)
    try:
        session_run = await svc.resume_session(
            x_tenant_id,
            req.session_id,
            checkpoint_id,
            resolution=req.resolution,
            resolved_by=req.resolved_by,
            comment=req.comment,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await db.commit()
    return {"ok": True, "data": _serialize_session(session_run)}


# ─────────────────────────────────────────────────────────────────────────────
# Session CRUD 路由
# ─────────────────────────────────────────────────────────────────────────────

@router.post("")
async def create_session(
    req: CreateSessionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """创建新的 Session 运行实例。"""
    svc = SessionRuntimeService(db)
    session_run = await svc.create_session(
        x_tenant_id,
        agent_template_name=req.agent_template_name,
        store_id=req.store_id,
        trigger_type=req.trigger_type,
        trigger_data=req.trigger_data,
    )
    await db.commit()
    return {"ok": True, "data": _serialize_session(session_run)}


@router.get("")
async def list_sessions(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
    store_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    agent_template_name: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """列出 Sessions（分页+过滤）。"""
    svc = SessionRuntimeService(db)
    items, total = await svc.list_sessions(
        x_tenant_id,
        store_id=store_id,
        status=status,
        agent_template_name=agent_template_name,
        page=page,
        size=size,
    )
    return {
        "ok": True,
        "data": {
            "items": [_serialize_session(s) for s in items],
            "total": total,
        },
    }


@router.get("/{session_id}")
async def get_session(
    session_id: UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """获取 Session 详情。"""
    svc = SessionRuntimeService(db)
    session_run = await svc.get_session(x_tenant_id, session_id)
    if session_run is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return {"ok": True, "data": _serialize_session(session_run)}


@router.post("/{session_id}/start")
async def start_session(
    session_id: UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """启动 Session（created → running）。"""
    svc = SessionRuntimeService(db)
    try:
        session_run = await svc.start_session(x_tenant_id, session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await db.commit()
    return {"ok": True, "data": _serialize_session(session_run)}


@router.post("/{session_id}/pause")
async def pause_session(
    session_id: UUID,
    req: PauseSessionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """暂停 Session（running → paused）。"""
    svc = SessionRuntimeService(db)
    try:
        checkpoint = await svc.pause_session(
            x_tenant_id,
            session_id,
            step_id=req.step_id,
            agent_id=req.agent_id,
            reason=req.reason,
            reason_detail=req.reason_detail,
            checkpoint_data=req.checkpoint_data,
            pending_action=req.pending_action,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await db.commit()
    return {"ok": True, "data": _serialize_checkpoint(checkpoint)}


@router.post("/{session_id}/cancel")
async def cancel_session(
    session_id: UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """取消 Session（created/running/paused → cancelled）。"""
    svc = SessionRuntimeService(db)
    try:
        session_run = await svc.cancel_session(x_tenant_id, session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await db.commit()
    return {"ok": True, "data": _serialize_session(session_run)}


# ─────────────────────────────────────────────────────────────────────────────
# Checkpoint 查询
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{session_id}/checkpoints")
async def get_session_checkpoints(
    session_id: UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """获取 Session 的所有 checkpoint。"""
    svc = SessionRuntimeService(db)
    try:
        checkpoints = await svc.get_session_checkpoints(x_tenant_id, session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {"ok": True, "data": [_serialize_checkpoint(c) for c in checkpoints]}


# ─────────────────────────────────────────────────────────────────────────────
# Timeline
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{session_id}/timeline")
async def get_session_timeline(
    session_id: UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """获取 Session 的完整事件时间线（按 sequence_no 排序）。"""
    svc = SessionRuntimeService(db)
    try:
        events = await svc.get_session_timeline(x_tenant_id, session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {"ok": True, "data": [_serialize_event(e) for e in events]}
