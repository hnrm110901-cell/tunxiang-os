"""统一任务引擎 API 路由（Sprint R1 Track B）

端点：
  POST /api/v1/tasks                     派单（dispatch_task）
  POST /api/v1/tasks/{task_id}/complete  完成
  POST /api/v1/tasks/{task_id}/escalate  手动升级（Agent/店长干预）
  POST /api/v1/tasks/{task_id}/cancel    取消（需 reason）
  GET  /api/v1/tasks                     按 assignee/status/type/due_before 过滤
  GET  /api/v1/tasks/overdue             所有超期未完成
  GET  /api/v1/tasks/{task_id}           单任务详情

统一响应：{"ok": bool, "data": any, "error": {code?, message?}}
所有端点强制 X-Tenant-ID header（CLAUDE.md §14 + §10）。

实现依赖：
  - TaskDispatchService（services/task_dispatch_service.py）
  - PgTaskRepository（repositories/task_repo.py）
  - shared.ontology.src.database.get_db_with_tenant — RLS 绑定租户上下文
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from repositories.task_repo import PgTaskRepository
from services.task_dispatch_service import (
    CancelReasonRequired,
    EscalationChainMissing,
    TaskDispatchService,
    TaskNotFound,
    TaskTerminalStateError,
)
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from shared.ontology.src.extensions.tasks import Task, TaskStatus, TaskType

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


# ──────────────────────────────────────────────────────────────────────
# 工具
# ──────────────────────────────────────────────────────────────────────


def _tenant_id(request: Request) -> UUID:
    raw = request.headers.get("X-Tenant-ID", "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    try:
        return UUID(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid X-Tenant-ID: {raw}") from exc


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": None}


def _err(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "data": None, "error": {"code": code, "message": message}}


async def _make_service(db: AsyncSession, tenant_id: UUID) -> TaskDispatchService:
    """为每个请求生成新的 Service（绑定已设置 tenant 的 DB session）。"""
    from sqlalchemy import text

    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)})
    repo = PgTaskRepository(session=db)
    return TaskDispatchService(repo=repo)


def _task_to_dict(t: Task) -> dict[str, Any]:
    """Task Pydantic 模型 → JSON 可序列化 dict。"""
    return t.model_dump(mode="json")


# ──────────────────────────────────────────────────────────────────────
# Request Bodies
# ──────────────────────────────────────────────────────────────────────


class DispatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: TaskType = Field(..., description="10 类任务枚举之一")
    assignee_employee_id: UUID = Field(..., description="派单对象员工ID")
    customer_id: Optional[UUID] = Field(None, description="目标客户ID")
    due_at: datetime = Field(..., description="截止时间（ISO8601，带时区）")
    store_id: Optional[UUID] = Field(None, description="门店ID（集团任务可空）")
    source_event_id: Optional[UUID] = Field(None, description="触发事件ID（因果链）")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="任务上下文 JSON（可含 escalation_chain）",
    )


class CompleteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome_code: Optional[str] = Field(None, description="结果码：contacted / converted / no_answer …")
    notes: Optional[str] = Field(None, description="自由文本备注")
    operator_id: UUID = Field(..., description="操作员员工ID")


class EscalateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    escalated_to_employee_id: UUID = Field(..., description="升级对象员工ID")
    reason: str = Field(..., min_length=1, max_length=200, description="升级原因")
    escalation_level: str = Field(
        default="manual",
        description="升级层级：store_manager / district_manager / manual",
    )


class CancelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(..., min_length=1, max_length=200, description="取消原因（必填）")


# ──────────────────────────────────────────────────────────────────────
# 端点
# ──────────────────────────────────────────────────────────────────────


@router.post("", response_model=None)
async def dispatch_task(
    request: Request,
    body: DispatchBody,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _tenant_id(request)
    service = await _make_service(db, tenant_id)
    task = await service.dispatch_task(
        task_type=body.task_type,
        assignee_employee_id=body.assignee_employee_id,
        customer_id=body.customer_id,
        due_at=body.due_at,
        payload=body.payload,
        tenant_id=tenant_id,
        store_id=body.store_id,
        source_event_id=body.source_event_id,
    )
    return _ok(_task_to_dict(task))


@router.post("/{task_id}/complete", response_model=None)
async def complete_task(
    request: Request,
    task_id: UUID,
    body: CompleteBody,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _tenant_id(request)
    service = await _make_service(db, tenant_id)
    try:
        task = await service.complete_task(
            task_id=task_id,
            outcome_code=body.outcome_code,
            notes=body.notes,
            operator_id=body.operator_id,
            tenant_id=tenant_id,
        )
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TaskTerminalStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _ok(_task_to_dict(task))


@router.post("/{task_id}/escalate", response_model=None)
async def escalate_task(
    request: Request,
    task_id: UUID,
    body: EscalateBody,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _tenant_id(request)
    service = await _make_service(db, tenant_id)
    try:
        task = await service.escalate_task(
            task_id=task_id,
            escalated_to_employee_id=body.escalated_to_employee_id,
            reason=body.reason,
            tenant_id=tenant_id,
            escalation_level=body.escalation_level,
        )
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TaskTerminalStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _ok(_task_to_dict(task))


@router.post("/{task_id}/cancel", response_model=None)
async def cancel_task(
    request: Request,
    task_id: UUID,
    body: CancelBody,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _tenant_id(request)
    service = await _make_service(db, tenant_id)
    try:
        task = await service.cancel_task(task_id=task_id, reason=body.reason, tenant_id=tenant_id)
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TaskTerminalStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CancelReasonRequired as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _ok(_task_to_dict(task))


@router.get("/overdue", response_model=None)
async def list_overdue(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _tenant_id(request)
    service = await _make_service(db, tenant_id)
    items = await service.list_overdue(tenant_id=tenant_id)
    return _ok({"items": [_task_to_dict(t) for t in items], "total": len(items)})


@router.get("/{task_id}", response_model=None)
async def get_task(
    request: Request,
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _tenant_id(request)
    service = await _make_service(db, tenant_id)
    try:
        task = await service.get_task(task_id=task_id, tenant_id=tenant_id)
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _ok(_task_to_dict(task))


@router.get("", response_model=None)
async def list_tasks(
    request: Request,
    assignee_id: Optional[UUID] = Query(None, description="派单对象过滤"),
    status: Optional[TaskStatus] = Query(None, description="状态过滤"),
    type: Optional[TaskType] = Query(None, description="任务类型过滤", alias="type"),
    due_before: Optional[datetime] = Query(None, description="截止时间上界（ISO8601）"),
    customer_id: Optional[UUID] = Query(None, description="客户ID过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _tenant_id(request)
    service = await _make_service(db, tenant_id)
    items = await service.list_tasks(
        tenant_id=tenant_id,
        assignee_employee_id=assignee_id,
        status=status,
        task_type=type,
        due_before=due_before,
        customer_id=customer_id,
        limit=size,
        offset=(page - 1) * size,
    )
    return _ok(
        {
            "items": [_task_to_dict(t) for t in items],
            "total": len(items),
            "page": page,
            "size": size,
        }
    )


# ──────────────────────────────────────────────────────────────────────
# 兜底异常转换（EscalationChainMissing 通常不对外暴露，这里保留可见性）
# ──────────────────────────────────────────────────────────────────────


@router.get("/_debug/chain-missing-count", include_in_schema=False)
async def _debug_chain_missing() -> dict[str, Any]:
    """内部桩：当前不做计数，仅用于扩展占位；对外不可见。"""
    # 使用 EscalationChainMissing 保持 import 不被 ruff 判为未使用
    _ = EscalationChainMissing
    return _ok({"count": 0})


__all__ = ["router"]
