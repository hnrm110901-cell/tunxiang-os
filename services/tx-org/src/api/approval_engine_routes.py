"""审批流引擎 API 路由（v3）

基于 approval_flow_templates + approval_flow_nodes +
     approval_instances + approval_node_instances 四张表。

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。

端点列表：
  ─ 审批流模板管理 ─
  POST   /api/v1/approval-engine/templates                          — 创建模板
  GET    /api/v1/approval-engine/templates                          — 模板列表
  GET    /api/v1/approval-engine/templates/{id}                     — 模板详情（含节点）
  PUT    /api/v1/approval-engine/templates/{id}                     — 更新模板
  POST   /api/v1/approval-engine/templates/{id}/nodes               — 添加节点
  PUT    /api/v1/approval-engine/templates/{id}/nodes/{node_order}  — 更新节点

  ─ 审批实例（工作台）─
  POST   /api/v1/approval-engine/instances                 — 发起审批
  GET    /api/v1/approval-engine/instances/my-pending      — 我待审批的（审批人视角）
  GET    /api/v1/approval-engine/instances/my-initiated    — 我发起的（申请人视角）
  GET    /api/v1/approval-engine/instances/{id}            — 审批详情（含节点时间线）
  POST   /api/v1/approval-engine/instances/{id}/approve    — 同意
  POST   /api/v1/approval-engine/instances/{id}/reject     — 拒绝
  POST   /api/v1/approval-engine/instances/{id}/cancel     — 撤回（仅申请人，pending状态）

  ─ 运维 ─
  POST   /api/v1/approval-engine/check-timeouts            — 超时检查（定时任务触发）

# ROUTER REGISTRATION:
# from .api.approval_engine_routes import router as approval_engine_router
# app.include_router(approval_engine_router, prefix="/api/v1/approval-engine")
"""

from __future__ import annotations

import json
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..models.approval_flow_engine import (
    VALID_BUSINESS_TYPES,
    ApproveReq,
    CancelReq,
    CreateInstanceReq,
    CreateNodeReq,
    CreateTemplateReq,
    RejectReq,
    UpdateTemplateReq,
)
from ..services.approval_engine import ApprovalEngine

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(tags=["approval-engine-v3"])

# 全局引擎实例（无状态，安全复用）
_engine = ApprovalEngine()


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get(
        "X-Tenant-ID", ""
    )
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": None}


def _row_to_dict(row: Any) -> dict[str, Any]:
    """将 SQLAlchemy Row/Mapping 转为可序列化 dict"""
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif not isinstance(v, (str, int, float, bool, dict, list, type(None))):
            d[k] = str(v)
    return d


async def _fetch_template_nodes(
    template_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """查询模板节点列表"""
    rows = await db.execute(
        text(
            "SELECT id, node_order, node_name, node_type, "
            "       approver_role_level, approver_role_id, approver_employee_id, "
            "       approve_type, auto_approve_condition, timeout_hours, timeout_action "
            "FROM approval_flow_nodes "
            "WHERE template_id = :tmpl_id AND tenant_id = :tid "
            "ORDER BY node_order ASC"
        ),
        {"tmpl_id": template_id, "tid": tenant_id},
    )
    return [_row_to_dict(r) for r in rows.mappings().fetchall()]


# ── 审批流模板管理 ────────────────────────────────────────────────────────────


@router.post("/templates")
async def create_template(
    req: CreateTemplateReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/approval-engine/templates — 创建审批流模板"""
    tenant_id = _get_tenant_id(request)

    if req.business_type not in VALID_BUSINESS_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"不支持的业务类型: {req.business_type}，"
                f"支持: {', '.join(sorted(VALID_BUSINESS_TYPES))}"
            ),
        )

    trigger_json = json.dumps(req.trigger_conditions, ensure_ascii=False)

    result = await db.execute(
        text(
            "INSERT INTO approval_flow_templates "
            "(tenant_id, template_name, business_type, trigger_conditions) "
            "VALUES (:tid, :name, :bt, :trigger::jsonb) "
            "RETURNING id, tenant_id, template_name, business_type, "
            "          trigger_conditions, is_active, created_at"
        ),
        {
            "tid": tenant_id,
            "name": req.template_name,
            "bt": req.business_type,
            "trigger": trigger_json,
        },
    )
    template = _row_to_dict(result.mappings().first())
    template_id = str(template["id"])

    # 批量插入节点
    for node in req.nodes:
        await _insert_node(template_id, node, tenant_id, db)

    await db.commit()
    template["nodes"] = await _fetch_template_nodes(template_id, tenant_id, db)
    return _ok(template)


@router.get("/templates")
async def list_templates(
    request: Request,
    business_type: Optional[str] = Query(None, description="按业务类型过滤"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/approval-engine/templates — 模板列表"""
    tenant_id = _get_tenant_id(request)

    if business_type:
        rows = await db.execute(
            text(
                "SELECT id, template_name, business_type, trigger_conditions, "
                "       is_active, created_at, updated_at "
                "FROM approval_flow_templates "
                "WHERE tenant_id = :tid AND business_type = :bt "
                "ORDER BY created_at DESC"
            ),
            {"tid": tenant_id, "bt": business_type},
        )
    else:
        rows = await db.execute(
            text(
                "SELECT id, template_name, business_type, trigger_conditions, "
                "       is_active, created_at, updated_at "
                "FROM approval_flow_templates "
                "WHERE tenant_id = :tid "
                "ORDER BY business_type, created_at DESC"
            ),
            {"tid": tenant_id},
        )

    items = [_row_to_dict(r) for r in rows.mappings().fetchall()]
    return _ok({"items": items, "total": len(items)})


@router.get("/templates/{template_id}")
async def get_template(
    template_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/approval-engine/templates/{id} — 模板详情（含节点列表）"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await _engine.get_template_with_nodes(template_id, tenant_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _ok(result)


@router.put("/templates/{template_id}")
async def update_template(
    template_id: str,
    req: UpdateTemplateReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """PUT /api/v1/approval-engine/templates/{id} — 更新模板"""
    tenant_id = _get_tenant_id(request)

    exist = await db.execute(
        text(
            "SELECT id FROM approval_flow_templates "
            "WHERE id = :id AND tenant_id = :tid"
        ),
        {"id": template_id, "tid": tenant_id},
    )
    if not exist.first():
        raise HTTPException(status_code=404, detail=f"模板不存在: {template_id}")

    set_parts = ["updated_at = NOW()"]
    params: dict[str, Any] = {"id": template_id, "tid": tenant_id}

    if req.template_name is not None:
        set_parts.append("template_name = :name")
        params["name"] = req.template_name
    if req.trigger_conditions is not None:
        set_parts.append("trigger_conditions = :trigger::jsonb")
        params["trigger"] = json.dumps(req.trigger_conditions, ensure_ascii=False)
    if req.is_active is not None:
        set_parts.append("is_active = :is_active")
        params["is_active"] = req.is_active

    await db.execute(
        text(
            f"UPDATE approval_flow_templates "
            f"SET {', '.join(set_parts)} "
            f"WHERE id = :id AND tenant_id = :tid"
        ),
        params,
    )
    await db.commit()

    try:
        result = await _engine.get_template_with_nodes(template_id, tenant_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _ok(result)


@router.post("/templates/{template_id}/nodes")
async def add_node(
    template_id: str,
    req: CreateNodeReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/approval-engine/templates/{id}/nodes — 添加节点"""
    tenant_id = _get_tenant_id(request)

    exist = await db.execute(
        text(
            "SELECT id FROM approval_flow_templates "
            "WHERE id = :id AND tenant_id = :tid"
        ),
        {"id": template_id, "tid": tenant_id},
    )
    if not exist.first():
        raise HTTPException(status_code=404, detail=f"模板不存在: {template_id}")

    # 检查 node_order 是否已占用
    order_exist = await db.execute(
        text(
            "SELECT id FROM approval_flow_nodes "
            "WHERE template_id = :tmpl_id AND node_order = :order AND tenant_id = :tid"
        ),
        {"tmpl_id": template_id, "order": req.node_order, "tid": tenant_id},
    )
    if order_exist.first():
        raise HTTPException(
            status_code=409,
            detail=(
                f"节点序号 {req.node_order} 已存在，"
                f"请使用 PUT .../nodes/{req.node_order} 更新或选择其他序号"
            ),
        )

    node = await _insert_node(template_id, req, tenant_id, db)
    await db.commit()
    return _ok(node)


@router.put("/templates/{template_id}/nodes/{node_order}")
async def update_node(
    template_id: str,
    node_order: int,
    req: CreateNodeReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """PUT /api/v1/approval-engine/templates/{id}/nodes/{node_order} — 更新节点"""
    tenant_id = _get_tenant_id(request)

    exist = await db.execute(
        text(
            "SELECT id FROM approval_flow_nodes "
            "WHERE template_id = :tmpl_id AND node_order = :order AND tenant_id = :tid"
        ),
        {"tmpl_id": template_id, "order": node_order, "tid": tenant_id},
    )
    if not exist.first():
        raise HTTPException(
            status_code=404,
            detail=f"节点不存在: template={template_id}, node_order={node_order}",
        )

    auto_cond_json = (
        json.dumps(req.auto_approve_condition.model_dump(), ensure_ascii=False)
        if req.auto_approve_condition
        else None
    )
    await db.execute(
        text(
            "UPDATE approval_flow_nodes "
            "SET node_name = :name, node_type = :ntype, "
            "    approver_role_level = :role_level, approver_role_id = :role_id, "
            "    approver_employee_id = :emp_id, approve_type = :approve_type, "
            "    auto_approve_condition = :auto_cond::jsonb, "
            "    timeout_hours = :timeout_hours, timeout_action = :timeout_action "
            "WHERE template_id = :tmpl_id AND node_order = :order AND tenant_id = :tid"
        ),
        {
            "name": req.node_name,
            "ntype": req.node_type,
            "role_level": req.approver_role_level,
            "role_id": str(req.approver_role_id) if req.approver_role_id else None,
            "emp_id": str(req.approver_employee_id) if req.approver_employee_id else None,
            "approve_type": req.approve_type,
            "auto_cond": auto_cond_json,
            "timeout_hours": req.timeout_hours,
            "timeout_action": req.timeout_action,
            "tmpl_id": template_id,
            "order": node_order,
            "tid": tenant_id,
        },
    )
    await db.commit()

    row = await db.execute(
        text(
            "SELECT id, node_order, node_name, node_type, "
            "       approver_role_level, approver_role_id, approver_employee_id, "
            "       approve_type, auto_approve_condition, timeout_hours, timeout_action "
            "FROM approval_flow_nodes "
            "WHERE template_id = :tmpl_id AND node_order = :order AND tenant_id = :tid"
        ),
        {"tmpl_id": template_id, "order": node_order, "tid": tenant_id},
    )
    return _ok(_row_to_dict(row.mappings().first()))


async def _insert_node(
    template_id: str,
    req: CreateNodeReq,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """插入节点，返回节点 dict（不 commit）"""
    auto_cond_json = (
        json.dumps(req.auto_approve_condition.model_dump(), ensure_ascii=False)
        if req.auto_approve_condition
        else None
    )
    result = await db.execute(
        text(
            "INSERT INTO approval_flow_nodes "
            "(tenant_id, template_id, node_order, node_name, node_type, "
            " approver_role_level, approver_role_id, approver_employee_id, "
            " approve_type, auto_approve_condition, timeout_hours, timeout_action) "
            "VALUES (:tid, :tmpl_id, :order, :name, :ntype, "
            "        :role_level, :role_id, :emp_id, "
            "        :approve_type, :auto_cond::jsonb, :timeout_hours, :timeout_action) "
            "RETURNING id, node_order, node_name, node_type, "
            "          approver_role_level, approver_role_id, approver_employee_id, "
            "          approve_type, auto_approve_condition, timeout_hours, timeout_action"
        ),
        {
            "tid": tenant_id,
            "tmpl_id": template_id,
            "order": req.node_order,
            "name": req.node_name,
            "ntype": req.node_type,
            "role_level": req.approver_role_level,
            "role_id": str(req.approver_role_id) if req.approver_role_id else None,
            "emp_id": str(req.approver_employee_id) if req.approver_employee_id else None,
            "approve_type": req.approve_type,
            "auto_cond": auto_cond_json,
            "timeout_hours": req.timeout_hours,
            "timeout_action": req.timeout_action,
        },
    )
    return _row_to_dict(result.mappings().first())


# ── 审批实例（工作台）────────────────────────────────────────────────────────


@router.post("/instances")
async def create_instance(
    req: CreateInstanceReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/approval-engine/instances — 发起审批"""
    tenant_id = _get_tenant_id(request)
    try:
        instance = await _engine.create_instance(
            template_id=str(req.template_id),
            business_type=req.business_type,
            business_id=req.business_id,
            initiator_id=str(req.initiator_id),
            store_id=str(req.store_id),
            title=req.title,
            summary=req.summary,
            tenant_id=tenant_id,
            db=db,
        )
        return _ok(instance)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/instances/my-pending")
async def list_my_pending(
    request: Request,
    approver_id: str = Query(..., description="审批人员工 ID"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    GET /api/v1/approval-engine/instances/my-pending — 我待审批的

    通过 approval_node_instances 找到当前人有 pending 记录的所有 pending 实例。
    """
    tenant_id = _get_tenant_id(request)
    offset = (page - 1) * size

    rows = await db.execute(
        text(
            "SELECT DISTINCT ai.id, ai.business_type, ai.business_id, ai.title, "
            "       ai.status, ai.current_node_order, ai.store_id, "
            "       ai.initiator_id, ai.summary, ai.created_at, ai.updated_at "
            "FROM approval_instances ai "
            "JOIN approval_node_instances ani "
            "    ON ani.instance_id = ai.id AND ani.tenant_id = ai.tenant_id "
            "WHERE ai.tenant_id = :tid AND ai.status = :status "
            "AND ai.is_deleted = FALSE "
            "AND ani.approver_id = :approver_id AND ani.status = :node_pending "
            "ORDER BY ai.created_at ASC "
            "LIMIT :size OFFSET :offset"
        ),
        {
            "tid": tenant_id,
            "status": "pending",
            "approver_id": approver_id,
            "node_pending": "pending",
            "size": size,
            "offset": offset,
        },
    )
    count_row = await db.execute(
        text(
            "SELECT COUNT(DISTINCT ai.id) "
            "FROM approval_instances ai "
            "JOIN approval_node_instances ani "
            "    ON ani.instance_id = ai.id AND ani.tenant_id = ai.tenant_id "
            "WHERE ai.tenant_id = :tid AND ai.status = :status "
            "AND ai.is_deleted = FALSE "
            "AND ani.approver_id = :approver_id AND ani.status = :node_pending"
        ),
        {
            "tid": tenant_id,
            "status": "pending",
            "approver_id": approver_id,
            "node_pending": "pending",
        },
    )
    items = [_row_to_dict(r) for r in rows.mappings().fetchall()]
    total = count_row.scalar() or 0
    return _ok({"items": items, "total": int(total)})


@router.get("/instances/my-initiated")
async def list_my_initiated(
    request: Request,
    initiator_id: str = Query(..., description="发起人员工 ID"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    GET /api/v1/approval-engine/instances/my-initiated — 我发起的

    返回该发起人创建的所有新式审批实例（含各状态）。
    """
    tenant_id = _get_tenant_id(request)
    offset = (page - 1) * size

    rows = await db.execute(
        text(
            "SELECT id, business_type, business_id, title, "
            "       status, current_node_order, store_id, "
            "       initiator_id, summary, created_at, updated_at, completed_at "
            "FROM approval_instances "
            "WHERE tenant_id = :tid AND initiator_id = :uid "
            "AND is_deleted = FALSE "
            "AND flow_template_id IS NOT NULL "
            "ORDER BY created_at DESC "
            "LIMIT :size OFFSET :offset"
        ),
        {"tid": tenant_id, "uid": initiator_id, "size": size, "offset": offset},
    )
    count_row = await db.execute(
        text(
            "SELECT COUNT(*) FROM approval_instances "
            "WHERE tenant_id = :tid AND initiator_id = :uid "
            "AND is_deleted = FALSE AND flow_template_id IS NOT NULL"
        ),
        {"tid": tenant_id, "uid": initiator_id},
    )
    items = [_row_to_dict(r) for r in rows.mappings().fetchall()]
    total = count_row.scalar() or 0
    return _ok({"items": items, "total": int(total)})


@router.get("/instances/{instance_id}")
async def get_instance(
    instance_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/approval-engine/instances/{id} — 审批详情（含节点时间线）"""
    tenant_id = _get_tenant_id(request)

    inst_row = await db.execute(
        text(
            "SELECT ai.id, ai.tenant_id, ai.flow_template_id, "
            "       ai.business_type, ai.business_id, ai.title, ai.initiator_id, "
            "       ai.store_id, ai.current_node_order, ai.status, ai.summary, "
            "       ai.created_at, ai.updated_at, ai.completed_at, "
            "       aft.template_name "
            "FROM approval_instances ai "
            "LEFT JOIN approval_flow_templates aft "
            "    ON aft.id = ai.flow_template_id "
            "WHERE ai.id = :iid AND ai.tenant_id = :tid AND ai.is_deleted = FALSE"
        ),
        {"iid": instance_id, "tid": tenant_id},
    )
    inst = inst_row.mappings().first()
    if not inst:
        raise HTTPException(status_code=404, detail=f"审批实例不存在: {instance_id}")

    instance_dict = _row_to_dict(inst)
    template_id = str(instance_dict.get("flow_template_id") or "")

    # 附加模板节点配置（流程图用）
    if template_id:
        instance_dict["template_nodes"] = await _fetch_template_nodes(
            template_id, tenant_id, db
        )

    # 查询节点审批时间线
    timeline_rows = await db.execute(
        text(
            "SELECT ani.id, ani.node_order, ani.approver_id, ani.status, "
            "       ani.comment, ani.decided_at, ani.created_at, "
            "       afn.node_name "
            "FROM approval_node_instances ani "
            "LEFT JOIN approval_flow_nodes afn "
            "    ON afn.template_id = :tmpl_id "
            "    AND afn.node_order = ani.node_order "
            "WHERE ani.instance_id = :iid AND ani.tenant_id = :tid "
            "ORDER BY ani.node_order ASC, ani.created_at ASC"
        ),
        {"iid": instance_id, "tid": tenant_id, "tmpl_id": template_id or ""},
    )
    instance_dict["timeline"] = [
        _row_to_dict(r) for r in timeline_rows.mappings().fetchall()
    ]

    return _ok(instance_dict)


@router.post("/instances/{instance_id}/approve")
async def approve_instance(
    instance_id: str,
    req: ApproveReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/approval-engine/instances/{id}/approve — 同意"""
    tenant_id = _get_tenant_id(request)

    # 取当前节点序号（避免客户端传错）
    inst = await db.execute(
        text(
            "SELECT current_node_order FROM approval_instances "
            "WHERE id = :iid AND tenant_id = :tid AND is_deleted = FALSE"
        ),
        {"iid": instance_id, "tid": tenant_id},
    )
    row = inst.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"审批实例不存在: {instance_id}")

    node_order = int(row["current_node_order"] or 1)

    try:
        result = await _engine.approve(
            instance_id=instance_id,
            node_order=node_order,
            approver_id=str(req.approver_id),
            comment=req.comment,
            tenant_id=tenant_id,
            db=db,
        )
        return _ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/instances/{instance_id}/reject")
async def reject_instance(
    instance_id: str,
    req: RejectReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/approval-engine/instances/{id}/reject — 拒绝"""
    tenant_id = _get_tenant_id(request)

    inst = await db.execute(
        text(
            "SELECT current_node_order FROM approval_instances "
            "WHERE id = :iid AND tenant_id = :tid AND is_deleted = FALSE"
        ),
        {"iid": instance_id, "tid": tenant_id},
    )
    row = inst.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"审批实例不存在: {instance_id}")

    node_order = int(row["current_node_order"] or 1)

    try:
        result = await _engine.reject(
            instance_id=instance_id,
            node_order=node_order,
            approver_id=str(req.approver_id),
            comment=req.comment,
            tenant_id=tenant_id,
            db=db,
        )
        return _ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/instances/{instance_id}/cancel")
async def cancel_instance(
    instance_id: str,
    req: CancelReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/approval-engine/instances/{id}/cancel — 撤回（仅发起人，pending 状态可撤）"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await _engine.cancel(
            instance_id=instance_id,
            initiator_id=str(req.initiator_id),
            tenant_id=tenant_id,
            db=db,
        )
        return _ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── 运维端点 ──────────────────────────────────────────────────────────────────


@router.post("/check-timeouts")
async def check_timeouts(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/approval-engine/check-timeouts — 超时检查（供定时任务触发）"""
    tenant_id = _get_tenant_id(request)
    result = await _engine.check_timeouts(tenant_id=tenant_id, db=db)
    return _ok(result)
