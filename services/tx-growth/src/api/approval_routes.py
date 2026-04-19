"""营销审批流 API

端点：
  GET  /api/v1/growth/approvals                    我的待审批列表（审批人视角）
  GET  /api/v1/growth/approvals/my-requests        我提交的审批列表（申请人视角）
  GET  /api/v1/growth/approvals/{id}               审批单详情
  POST /api/v1/growth/approvals/{id}/approve       审批通过
  POST /api/v1/growth/approvals/{id}/reject        审批拒绝
  POST /api/v1/growth/approvals/{id}/cancel        撤销申请（申请人）

  GET  /api/v1/growth/approvals/workflows          审批流模板列表
  POST /api/v1/growth/approvals/workflows          创建审批流模板
  POST /api/v1/growth/approvals/workflows/seed     插入内置默认模板（租户初始化用）
"""

import uuid
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Request
from models.approval import ApprovalRequest, ApprovalWorkflow
from pydantic import BaseModel, field_validator
from services.approval_service import ApprovalService
from sqlalchemy import and_, select

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/growth/approvals", tags=["approvals"])

_svc = ApprovalService()


# ---------------------------------------------------------------------------
# 统一响应
# ---------------------------------------------------------------------------


def ok_response(data: Any) -> dict:
    return {"ok": True, "data": data}


def error_response(msg: str, code: str = "ERROR") -> dict:
    return {"ok": False, "error": {"code": code, "message": msg}}


# ---------------------------------------------------------------------------
# 请求体模型
# ---------------------------------------------------------------------------


class ApproveRequest(BaseModel):
    approver_id: uuid.UUID
    comment: Optional[str] = None


class RejectRequest(BaseModel):
    approver_id: uuid.UUID
    reason: str

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("拒绝原因不能为空")
        return v.strip()


class CancelRequest(BaseModel):
    requester_id: uuid.UUID


class CreateWorkflowRequest(BaseModel):
    name: str
    trigger_conditions: dict
    steps: list[dict]
    is_active: bool = True
    priority: int = 0

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("审批流名称不能为空")
        return v.strip()

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, v: list) -> list:
        if not v:
            raise ValueError("审批步骤不能为空")
        for step in v:
            if "step" not in step or "role" not in step:
                raise ValueError("每个步骤必须包含 step 和 role 字段")
        return v


# ---------------------------------------------------------------------------
# 工作流模板端点（注意：固定路径段必须在 {id} 路径之前声明）
# ---------------------------------------------------------------------------


@router.get("/workflows")
async def list_workflows(
    request: Request,
    is_active: Optional[bool] = None,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """列出审批流模板"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    conditions = [
        ApprovalWorkflow.tenant_id == tenant_id,
        ApprovalWorkflow.is_deleted == False,  # noqa: E712
    ]
    if is_active is not None:
        conditions.append(ApprovalWorkflow.is_active == is_active)

    stmt = (
        select(ApprovalWorkflow)
        .where(and_(*conditions))
        .order_by(ApprovalWorkflow.priority.desc(), ApprovalWorkflow.created_at.desc())
    )
    result = await db.execute(stmt)
    workflows = result.scalars().all()

    return ok_response(
        {
            "items": [
                {
                    "workflow_id": str(wf.id),
                    "name": wf.name,
                    "trigger_conditions": wf.trigger_conditions,
                    "steps": wf.steps,
                    "is_active": wf.is_active,
                    "priority": wf.priority,
                    "created_at": wf.created_at.isoformat() if wf.created_at else None,
                }
                for wf in workflows
            ],
            "total": len(workflows),
        }
    )


@router.post("/workflows")
async def create_workflow(
    req: CreateWorkflowRequest,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建审批流模板"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    wf = ApprovalWorkflow(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=req.name,
        trigger_conditions=req.trigger_conditions,
        steps=req.steps,
        is_active=req.is_active,
        priority=req.priority,
    )
    db.add(wf)
    await db.commit()

    log.info(
        "approval.workflow_created",
        workflow_id=str(wf.id),
        name=wf.name,
        tenant_id=x_tenant_id,
    )
    return ok_response(
        {
            "workflow_id": str(wf.id),
            "name": wf.name,
            "is_active": wf.is_active,
            "priority": wf.priority,
        }
    )


@router.post("/workflows/seed")
async def seed_default_workflows(
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """为当前租户插入内置默认审批流模板（幂等，可重复调用）"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    result = await _svc.seed_default_workflows(tenant_id=tenant_id, db=db)
    await db.commit()
    return ok_response(result)


# ---------------------------------------------------------------------------
# 审批单端点
# ---------------------------------------------------------------------------


@router.get("")
async def list_pending_approvals(
    request: Request,
    role: Optional[str] = None,
    page: int = 1,
    size: int = 20,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """待审批列表（审批人视角，可按角色过滤；管理后台使用）"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    conditions = [
        ApprovalRequest.tenant_id == tenant_id,
        ApprovalRequest.status == "pending",
        ApprovalRequest.is_deleted == False,  # noqa: E712
    ]

    stmt = (
        select(ApprovalRequest)
        .where(and_(*conditions))
        .order_by(ApprovalRequest.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    result = await db.execute(stmt)
    requests = result.scalars().all()

    return ok_response(
        {
            "items": [_serialize_request(r) for r in requests],
            "page": page,
            "size": size,
        }
    )


@router.get("/my-requests")
async def list_my_requests(
    request: Request,
    requester_id: uuid.UUID,
    status: Optional[str] = None,
    page: int = 1,
    size: int = 20,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """我提交的审批列表（申请人视角）"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    conditions = [
        ApprovalRequest.tenant_id == tenant_id,
        ApprovalRequest.requester_id == requester_id,
        ApprovalRequest.is_deleted == False,  # noqa: E712
    ]
    if status:
        conditions.append(ApprovalRequest.status == status)

    stmt = (
        select(ApprovalRequest)
        .where(and_(*conditions))
        .order_by(ApprovalRequest.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    result = await db.execute(stmt)
    requests = result.scalars().all()

    return ok_response(
        {
            "items": [_serialize_request(r) for r in requests],
            "page": page,
            "size": size,
        }
    )


@router.get("/{request_id}")
async def get_approval_detail(
    request_id: uuid.UUID,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """审批单详情"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    stmt = select(ApprovalRequest).where(
        and_(
            ApprovalRequest.id == request_id,
            ApprovalRequest.tenant_id == tenant_id,
            ApprovalRequest.is_deleted == False,  # noqa: E712
        )
    )
    req = (await db.execute(stmt)).scalar_one_or_none()
    if req is None:
        raise HTTPException(status_code=404, detail="审批单不存在")

    return ok_response(_serialize_request(req, include_history=True))


@router.post("/{request_id}/approve")
async def approve_request(
    request_id: uuid.UUID,
    req: ApproveRequest,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """审批通过"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    try:
        result = await _svc.approve(
            request_id=request_id,
            approver_id=req.approver_id,
            comment=req.comment,
            tenant_id=tenant_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "审批失败"))

    await db.commit()
    log.info(
        "approval.approved_via_api",
        request_id=str(request_id),
        approver_id=str(req.approver_id),
        tenant_id=x_tenant_id,
    )
    return ok_response(result)


@router.post("/{request_id}/reject")
async def reject_request(
    request_id: uuid.UUID,
    req: RejectRequest,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """审批拒绝"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    try:
        result = await _svc.reject(
            request_id=request_id,
            approver_id=req.approver_id,
            reason=req.reason,
            tenant_id=tenant_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "拒绝操作失败"))

    await db.commit()
    log.info(
        "approval.rejected_via_api",
        request_id=str(request_id),
        approver_id=str(req.approver_id),
        tenant_id=x_tenant_id,
    )
    return ok_response(result)


@router.post("/{request_id}/cancel")
async def cancel_request(
    request_id: uuid.UUID,
    req: CancelRequest,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """撤销审批申请（申请人操作）"""
    tenant_id = uuid.UUID(x_tenant_id)
    db = request.state.db

    try:
        result = await _svc.cancel(
            request_id=request_id,
            requester_id=req.requester_id,
            tenant_id=tenant_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "撤销失败"))

    await db.commit()
    log.info(
        "approval.cancelled_via_api",
        request_id=str(request_id),
        requester_id=str(req.requester_id),
        tenant_id=x_tenant_id,
    )
    return ok_response(result)


# ---------------------------------------------------------------------------
# 序列化辅助
# ---------------------------------------------------------------------------


def _serialize_request(req: ApprovalRequest, include_history: bool = False) -> dict:
    data: dict = {
        "request_id": str(req.id),
        "workflow_id": str(req.workflow_id),
        "object_type": req.object_type,
        "object_id": req.object_id,
        "object_summary": req.object_summary,
        "requester_id": str(req.requester_id),
        "requester_name": req.requester_name,
        "status": req.status,
        "current_step": req.current_step,
        "reject_reason": req.reject_reason,
        "created_at": req.created_at.isoformat() if req.created_at else None,
        "approved_at": req.approved_at.isoformat() if req.approved_at else None,
        "expires_at": req.expires_at.isoformat() if req.expires_at else None,
    }
    if include_history:
        data["approval_history"] = req.approval_history
    return data
