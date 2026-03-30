"""通用审批引擎 API 路由

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。

# ROUTER REGISTRATION:
# from .api.approval_engine_routes import router as approval_engine_router
# app.include_router(approval_engine_router, prefix="/api/v1/approval-engine")
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..services.approval_engine import ApprovalEngine
from ..models.approval_flow import VALID_BUSINESS_TYPES

router = APIRouter(tags=["approval-engine"])


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get(
        "X-Tenant-ID", ""
    )
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


# ── 请求模型 ──────────────────────────────────────────────────────────────────


class StepConditionReq(BaseModel):
    field: str
    op: str
    value: float


class FlowStepReq(BaseModel):
    step: int = Field(..., ge=1)
    role: str
    timeout_hours: int = Field(default=48, ge=1)
    condition: Optional[StepConditionReq] = None


class CreateFlowReq(BaseModel):
    flow_name: str = Field(..., max_length=100)
    business_type: str
    steps: List[FlowStepReq] = Field(..., min_length=1)


class SubmitApprovalReq(BaseModel):
    flow_def_id: str
    source_id: Optional[str] = None
    title: str = Field(..., max_length=200)
    context: Dict[str, Any] = Field(default_factory=dict)
    initiator_id: str
    store_id: str
    amount: Optional[float] = None


class ApproveReq(BaseModel):
    approver_id: str
    comment: Optional[str] = None


class RejectReq(BaseModel):
    approver_id: str
    comment: Optional[str] = None


# ── 端点 ──────────────────────────────────────────────────────────────────────


@router.post("/flows")
async def create_flow(
    req: CreateFlowReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """POST /api/v1/approval-engine/flows — 创建审批流定义"""
    tenant_id = _get_tenant_id(request)

    if req.business_type not in VALID_BUSINESS_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的业务类型: {req.business_type}，"
            f"支持: {', '.join(sorted(VALID_BUSINESS_TYPES))}",
        )

    steps_json = json.dumps(
        [s.model_dump(exclude_none=False) for s in req.steps], ensure_ascii=False
    )

    result = await db.execute(
        text(
            "INSERT INTO approval_flow_definitions "
            "(tenant_id, flow_name, business_type, steps) "
            "VALUES (:tenant_id, :flow_name, :business_type, :steps::jsonb) "
            "RETURNING id, tenant_id, flow_name, business_type, steps, is_active, created_at"
        ),
        {
            "tenant_id": tenant_id,
            "flow_name": req.flow_name,
            "business_type": req.business_type,
            "steps": steps_json,
        },
    )
    await db.commit()
    row = dict(result.mappings().first())
    return _ok(row)


@router.get("/flows")
async def list_flows(
    request: Request,
    business_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """GET /api/v1/approval-engine/flows — 审批流列表"""
    tenant_id = _get_tenant_id(request)

    if business_type:
        rows = await db.execute(
            text(
                "SELECT id, flow_name, business_type, steps, is_active, created_at "
                "FROM approval_flow_definitions "
                "WHERE tenant_id = :tenant_id AND business_type = :bt AND is_active = TRUE "
                "ORDER BY created_at DESC"
            ),
            {"tenant_id": tenant_id, "bt": business_type},
        )
    else:
        rows = await db.execute(
            text(
                "SELECT id, flow_name, business_type, steps, is_active, created_at "
                "FROM approval_flow_definitions "
                "WHERE tenant_id = :tenant_id AND is_active = TRUE "
                "ORDER BY created_at DESC"
            ),
            {"tenant_id": tenant_id},
        )

    items = [dict(r) for r in rows.mappings().fetchall()]
    return _ok({"items": items, "total": len(items)})


@router.post("/submit")
async def submit_approval(
    req: SubmitApprovalReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """POST /api/v1/approval-engine/submit — 发起审批"""
    tenant_id = _get_tenant_id(request)
    try:
        instance = await ApprovalEngine.submit(
            flow_def_id=req.flow_def_id,
            source_id=req.source_id,
            title=req.title,
            context=req.context,
            initiator_id=req.initiator_id,
            store_id=req.store_id,
            tenant_id=tenant_id,
            db=db,
            amount=req.amount,
        )
        return _ok(instance)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/pending")
async def list_pending(
    request: Request,
    approver_id: str = Query(..., description="审批人 ID"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """GET /api/v1/approval-engine/pending?approver= — 我的待审批"""
    tenant_id = _get_tenant_id(request)
    offset = (page - 1) * size

    # 查询当前审批人所在角色匹配当前步骤的待审批实例
    # 简化实现：查询员工角色，再匹配流程定义步骤
    emp_row = await db.execute(
        text("SELECT role FROM employees WHERE id = :aid AND tenant_id = :tid AND is_deleted = FALSE"),
        {"aid": approver_id, "tid": tenant_id},
    )
    emp = emp_row.mappings().first()
    approver_role = emp["role"] if emp else None

    if not approver_role:
        return _ok({"items": [], "total": 0})

    # 查询 pending 实例中，流程当前步骤角色匹配审批人角色的实例
    rows = await db.execute(
        text(
            "SELECT ai.id, ai.title, ai.business_type, ai.status, "
            "ai.current_step, ai.amount, ai.store_id, ai.initiator_id, ai.created_at "
            "FROM approval_instances ai "
            "JOIN approval_flow_definitions afd ON ai.flow_def_id = afd.id "
            "WHERE ai.tenant_id = :tenant_id AND ai.status = 'pending' "
            "AND EXISTS ("
            "  SELECT 1 FROM jsonb_array_elements(afd.steps) AS s "
            "  WHERE (s->>'step')::int = ai.current_step "
            "  AND s->>'role' = :role"
            ") "
            "ORDER BY ai.created_at ASC "
            "LIMIT :size OFFSET :offset"
        ),
        {"tenant_id": tenant_id, "role": approver_role, "size": size, "offset": offset},
    )

    count_row = await db.execute(
        text(
            "SELECT COUNT(*) FROM approval_instances ai "
            "JOIN approval_flow_definitions afd ON ai.flow_def_id = afd.id "
            "WHERE ai.tenant_id = :tenant_id AND ai.status = 'pending' "
            "AND EXISTS ("
            "  SELECT 1 FROM jsonb_array_elements(afd.steps) AS s "
            "  WHERE (s->>'step')::int = ai.current_step "
            "  AND s->>'role' = :role"
            ")"
        ),
        {"tenant_id": tenant_id, "role": approver_role},
    )

    items = [dict(r) for r in rows.mappings().fetchall()]
    total = count_row.scalar() or 0
    return _ok({"items": items, "total": total})


@router.post("/{instance_id}/approve")
async def approve(
    instance_id: str,
    req: ApproveReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """POST /api/v1/approval-engine/{id}/approve — 同意"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await ApprovalEngine.approve(
            instance_id=instance_id,
            approver_id=req.approver_id,
            comment=req.comment,
            tenant_id=tenant_id,
            db=db,
        )
        return _ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{instance_id}/reject")
async def reject(
    instance_id: str,
    req: RejectReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """POST /api/v1/approval-engine/{id}/reject — 拒绝"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await ApprovalEngine.reject(
            instance_id=instance_id,
            approver_id=req.approver_id,
            comment=req.comment,
            tenant_id=tenant_id,
            db=db,
        )
        return _ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{instance_id}/history")
async def get_history(
    instance_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """GET /api/v1/approval-engine/{id}/history — 审批历史"""
    tenant_id = _get_tenant_id(request)

    instance_row = await db.execute(
        text(
            "SELECT id, title, business_type, status, current_step, amount, "
            "store_id, initiator_id, context, created_at, completed_at "
            "FROM approval_instances "
            "WHERE id = :id AND tenant_id = :tenant_id"
        ),
        {"id": instance_id, "tenant_id": tenant_id},
    )
    instance = instance_row.mappings().first()
    if not instance:
        raise HTTPException(status_code=404, detail=f"审批实例不存在: {instance_id}")

    records_row = await db.execute(
        text(
            "SELECT id, step, approver_id, action, comment, acted_at "
            "FROM approval_records "
            "WHERE instance_id = :instance_id AND tenant_id = :tenant_id "
            "ORDER BY acted_at ASC"
        ),
        {"instance_id": instance_id, "tenant_id": tenant_id},
    )
    records = [dict(r) for r in records_row.mappings().fetchall()]

    return _ok({"instance": dict(instance), "records": records})


@router.post("/check-timeouts")
async def check_timeouts(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """POST /api/v1/approval-engine/check-timeouts — 触发超时检查（催办）"""
    tenant_id = _get_tenant_id(request)
    result = await ApprovalEngine.check_timeouts(tenant_id=tenant_id, db=db)
    return _ok(result)
