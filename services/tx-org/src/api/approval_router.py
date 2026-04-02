"""审批流 API 路由（v2）

基于 approval_workflow_templates / approval_instances / approval_step_records。
统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。

端点列表：
  POST /api/v1/approvals                    发起审批
  GET  /api/v1/approvals                    审批列表（我发起的/待我审批的）
  GET  /api/v1/approvals/pending-count      待审批数量（用于 badge 显示）
  GET  /api/v1/approvals/{id}               审批详情（含步骤记录时间线）
  POST /api/v1/approvals/{id}/approve       通过
  POST /api/v1/approvals/{id}/reject        拒绝
  POST /api/v1/approvals/{id}/cancel        撤回（仅发起人，pending 状态可撤）

  GET  /api/v1/approval-templates           模板列表
  POST /api/v1/approval-templates           创建模板
  PUT  /api/v1/approval-templates/{id}      更新模板
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.approval_workflow_engine import (
    VALID_BUSINESS_TYPES,
    ApprovalEngine,
)

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(tags=["approvals"])


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


class TemplateStepReq(BaseModel):
    step: int = Field(..., ge=1, description="步骤序号，从 1 开始")
    approver_role: str = Field(..., description="审批角色，如 store_manager/area_director")
    timeout_hours: int = Field(default=24, ge=1, description="超时小时数")
    condition: StepConditionReq | None = Field(None, description="步骤条件，为空则无条件执行")


class CreateTemplateReq(BaseModel):
    name: str = Field(..., max_length=100)
    business_type: str
    steps: list[TemplateStepReq] = Field(..., min_length=1)
    conditions: dict[str, Any] = Field(
        default_factory=dict,
        description="模板匹配条件，如 {'amount': {'op': '>', 'value': 1000}}",
    )


class UpdateTemplateReq(BaseModel):
    name: str | None = Field(None, max_length=100)
    steps: list[TemplateStepReq] | None = None
    conditions: dict[str, Any] | None = None
    is_active: bool | None = None


class CreateInstanceReq(BaseModel):
    business_type: str = Field(..., description="业务类型")
    business_id: str = Field(..., description="关联业务单据 ID")
    title: str = Field(..., max_length=200, description="审批标题")
    initiator_id: str = Field(..., description="发起人员工 ID")
    context_data: dict[str, Any] = Field(
        default_factory=dict, description="业务上下文，用于条件路由"
    )


class ApproveReq(BaseModel):
    approver_id: str
    comment: str | None = None


class RejectReq(BaseModel):
    approver_id: str
    comment: str | None = None


class CancelReq(BaseModel):
    initiator_id: str = Field(..., description="发起人 ID，需与创建时一致")


# ── 审批实例端点 ───────────────────────────────────────────────────────────────


@router.post("/approvals")
async def create_approval(
    req: CreateInstanceReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """POST /api/v1/approvals — 发起审批"""
    tenant_id = _get_tenant_id(request)
    try:
        instance = await ApprovalEngine.create_instance(
            tenant_id=tenant_id,
            business_type=req.business_type,
            business_id=req.business_id,
            title=req.title,
            initiator_id=req.initiator_id,
            context_data=req.context_data,
            db=db,
        )
        return _ok(instance)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/approvals/pending-count")
async def get_pending_count(
    request: Request,
    approver_id: str = Query(..., description="审批人员工 ID，用于 badge 显示"),
    db: AsyncSession = Depends(get_db),
):
    """
    GET /api/v1/approvals/pending-count — 待审批数量

    返回该审批人当前待处理的审批数量，供 manager app badge 使用。
    """
    tenant_id = _get_tenant_id(request)

    # 查询审批人角色
    emp_row = await db.execute(
        text(
            "SELECT role FROM employees "
            "WHERE id = :aid AND tenant_id = :tid AND is_deleted = FALSE"
        ),
        {"aid": approver_id, "tid": tenant_id},
    )
    emp = emp_row.mappings().first()
    if not emp:
        return _ok({"count": 0})

    approver_role = emp["role"]

    count_row = await db.execute(
        text(
            "SELECT COUNT(*) FROM approval_instances ai "
            "LEFT JOIN approval_workflow_templates awt ON ai.template_id = awt.id "
            "WHERE ai.tenant_id = :tid AND ai.status = 'pending' "
            "AND ai.is_deleted = FALSE "
            "AND ("
            "  awt.id IS NULL "  # 无模板（降级为 store_manager）
            "  AND :role = 'store_manager' "
            "  OR EXISTS ("
            "    SELECT 1 FROM jsonb_array_elements(awt.steps) AS s "
            "    WHERE (s->>'step')::int = ai.current_step "
            "    AND s->>'approver_role' = :role"
            "  )"
            ")"
        ),
        {"tid": tenant_id, "role": approver_role},
    )
    count = count_row.scalar() or 0
    return _ok({"count": int(count)})


@router.get("/approvals")
async def list_approvals(
    request: Request,
    mode: str = Query(
        "pending_for_me",
        description="查询模式：pending_for_me=待我审批 | initiated_by_me=我发起的",
    ),
    approver_id: str = Query(..., description="当前操作人员工 ID"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """
    GET /api/v1/approvals — 审批列表

    mode=pending_for_me  待我审批（按角色匹配当前步骤）
    mode=initiated_by_me 我发起的（含各状态）
    """
    tenant_id = _get_tenant_id(request)
    offset = (page - 1) * size

    if mode == "initiated_by_me":
        rows = await db.execute(
            text(
                "SELECT id, business_type, business_id, title, status, "
                "current_step, context_data, created_at, completed_at "
                "FROM approval_instances "
                "WHERE tenant_id = :tid AND initiator_id = :uid "
                "AND is_deleted = FALSE "
                "ORDER BY created_at DESC "
                "LIMIT :size OFFSET :offset"
            ),
            {"tid": tenant_id, "uid": approver_id, "size": size, "offset": offset},
        )
        count_row = await db.execute(
            text(
                "SELECT COUNT(*) FROM approval_instances "
                "WHERE tenant_id = :tid AND initiator_id = :uid AND is_deleted = FALSE"
            ),
            {"tid": tenant_id, "uid": approver_id},
        )
    else:
        # 查询审批人角色
        emp_row = await db.execute(
            text(
                "SELECT role FROM employees "
                "WHERE id = :aid AND tenant_id = :tid AND is_deleted = FALSE"
            ),
            {"aid": approver_id, "tid": tenant_id},
        )
        emp = emp_row.mappings().first()
        if not emp:
            return _ok({"items": [], "total": 0})
        approver_role = emp["role"]

        rows = await db.execute(
            text(
                "SELECT ai.id, ai.business_type, ai.business_id, ai.title, ai.status, "
                "ai.current_step, ai.context_data, ai.created_at, ai.completed_at "
                "FROM approval_instances ai "
                "LEFT JOIN approval_workflow_templates awt ON ai.template_id = awt.id "
                "WHERE ai.tenant_id = :tid AND ai.status = 'pending' "
                "AND ai.is_deleted = FALSE "
                "AND ("
                "  (awt.id IS NULL AND :role = 'store_manager') "
                "  OR EXISTS ("
                "    SELECT 1 FROM jsonb_array_elements(awt.steps) AS s "
                "    WHERE (s->>'step')::int = ai.current_step "
                "    AND s->>'approver_role' = :role"
                "  )"
                ") "
                "ORDER BY ai.created_at ASC "
                "LIMIT :size OFFSET :offset"
            ),
            {"tid": tenant_id, "role": approver_role, "size": size, "offset": offset},
        )
        count_row = await db.execute(
            text(
                "SELECT COUNT(*) FROM approval_instances ai "
                "LEFT JOIN approval_workflow_templates awt ON ai.template_id = awt.id "
                "WHERE ai.tenant_id = :tid AND ai.status = 'pending' "
                "AND ai.is_deleted = FALSE "
                "AND ("
                "  (awt.id IS NULL AND :role = 'store_manager') "
                "  OR EXISTS ("
                "    SELECT 1 FROM jsonb_array_elements(awt.steps) AS s "
                "    WHERE (s->>'step')::int = ai.current_step "
                "    AND s->>'approver_role' = :role"
                "  )"
                ")"
            ),
            {"tid": tenant_id, "role": approver_role},
        )

    items = [dict(r) for r in rows.mappings().fetchall()]
    total = count_row.scalar() or 0
    return _ok({"items": items, "total": total})


@router.get("/approvals/{instance_id}")
async def get_approval(
    instance_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """GET /api/v1/approvals/{id} — 审批详情（含步骤记录时间线）"""
    tenant_id = _get_tenant_id(request)

    inst_row = await db.execute(
        text(
            "SELECT ai.id, ai.tenant_id, ai.template_id, ai.business_type, "
            "ai.business_id, ai.title, ai.initiator_id, ai.current_step, "
            "ai.status, ai.context_data, ai.created_at, ai.updated_at, ai.completed_at, "
            "awt.name AS template_name, awt.steps AS template_steps "
            "FROM approval_instances ai "
            "LEFT JOIN approval_workflow_templates awt ON ai.template_id = awt.id "
            "WHERE ai.id = :iid AND ai.tenant_id = :tid AND ai.is_deleted = FALSE"
        ),
        {"iid": instance_id, "tid": tenant_id},
    )
    inst = inst_row.mappings().first()
    if not inst:
        raise HTTPException(status_code=404, detail=f"审批实例不存在: {instance_id}")

    records_row = await db.execute(
        text(
            "SELECT id, step, approver_id, action, comment, acted_at, created_at "
            "FROM approval_step_records "
            "WHERE instance_id = :iid AND tenant_id = :tid "
            "ORDER BY acted_at ASC"
        ),
        {"iid": instance_id, "tid": tenant_id},
    )
    records = [dict(r) for r in records_row.mappings().fetchall()]

    return _ok({"instance": dict(inst), "timeline": records})


@router.post("/approvals/{instance_id}/approve")
async def approve_instance(
    instance_id: str,
    req: ApproveReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """POST /api/v1/approvals/{id}/approve — 通过"""
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


@router.post("/approvals/{instance_id}/reject")
async def reject_instance(
    instance_id: str,
    req: RejectReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """POST /api/v1/approvals/{id}/reject — 拒绝"""
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


@router.post("/approvals/{instance_id}/cancel")
async def cancel_instance(
    instance_id: str,
    req: CancelReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """POST /api/v1/approvals/{id}/cancel — 撤回（仅发起人，pending 状态可撤）"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await ApprovalEngine.cancel(
            instance_id=instance_id,
            initiator_id=req.initiator_id,
            tenant_id=tenant_id,
            db=db,
        )
        return _ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── 模板管理端点（总部配置）────────────────────────────────────────────────────


@router.get("/approval-templates")
async def list_templates(
    request: Request,
    business_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """GET /api/v1/approval-templates — 模板列表"""
    tenant_id = _get_tenant_id(request)

    if business_type:
        rows = await db.execute(
            text(
                "SELECT id, name, business_type, steps, conditions, is_active, created_at "
                "FROM approval_workflow_templates "
                "WHERE tenant_id = :tid AND business_type = :bt AND is_deleted = FALSE "
                "ORDER BY created_at DESC"
            ),
            {"tid": tenant_id, "bt": business_type},
        )
    else:
        rows = await db.execute(
            text(
                "SELECT id, name, business_type, steps, conditions, is_active, created_at "
                "FROM approval_workflow_templates "
                "WHERE tenant_id = :tid AND is_deleted = FALSE "
                "ORDER BY business_type, created_at DESC"
            ),
            {"tid": tenant_id},
        )

    items = [dict(r) for r in rows.mappings().fetchall()]
    return _ok({"items": items, "total": len(items)})


@router.post("/approval-templates")
async def create_template(
    req: CreateTemplateReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """POST /api/v1/approval-templates — 创建模板"""
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
    conditions_json = json.dumps(req.conditions, ensure_ascii=False)

    result = await db.execute(
        text(
            "INSERT INTO approval_workflow_templates "
            "(tenant_id, name, business_type, steps, conditions) "
            "VALUES (:tid, :name, :bt, :steps::jsonb, :cond::jsonb) "
            "RETURNING id, tenant_id, name, business_type, steps, conditions, "
            "          is_active, created_at, updated_at"
        ),
        {
            "tid": tenant_id,
            "name": req.name,
            "bt": req.business_type,
            "steps": steps_json,
            "cond": conditions_json,
        },
    )
    await db.commit()
    row = dict(result.mappings().first())
    return _ok(row)


@router.put("/approval-templates/{template_id}")
async def update_template(
    template_id: str,
    req: UpdateTemplateReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """PUT /api/v1/approval-templates/{id} — 更新模板"""
    tenant_id = _get_tenant_id(request)

    # 检查存在
    exist_row = await db.execute(
        text(
            "SELECT id FROM approval_workflow_templates "
            "WHERE id = :tid_tpl AND tenant_id = :tid AND is_deleted = FALSE"
        ),
        {"tid_tpl": template_id, "tid": tenant_id},
    )
    if not exist_row.first():
        raise HTTPException(status_code=404, detail=f"模板不存在: {template_id}")

    set_parts = ["updated_at = NOW()"]
    params: dict[str, Any] = {"tid_tpl": template_id, "tid": tenant_id}

    if req.name is not None:
        set_parts.append("name = :name")
        params["name"] = req.name
    if req.steps is not None:
        set_parts.append("steps = :steps::jsonb")
        params["steps"] = json.dumps(
            [s.model_dump(exclude_none=False) for s in req.steps], ensure_ascii=False
        )
    if req.conditions is not None:
        set_parts.append("conditions = :conditions::jsonb")
        params["conditions"] = json.dumps(req.conditions, ensure_ascii=False)
    if req.is_active is not None:
        set_parts.append("is_active = :is_active")
        params["is_active"] = req.is_active

    await db.execute(
        text(
            f"UPDATE approval_workflow_templates "
            f"SET {', '.join(set_parts)} "
            f"WHERE id = :tid_tpl AND tenant_id = :tid"
        ),
        params,
    )
    await db.commit()

    updated_row = await db.execute(
        text(
            "SELECT id, name, business_type, steps, conditions, is_active, created_at, updated_at "
            "FROM approval_workflow_templates "
            "WHERE id = :tid_tpl AND tenant_id = :tid"
        ),
        {"tid_tpl": template_id, "tid": tenant_id},
    )
    row = dict(updated_row.mappings().first())
    return _ok(row)
