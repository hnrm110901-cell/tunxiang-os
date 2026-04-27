"""折扣审批 API 路由 — 创建/批准/拒绝/查询

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.approval_service import ApprovalService

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


# ─── 请求模型 ───


class CreateApprovalReq(BaseModel):
    order_id: str
    discount_info: dict = Field(
        ...,
        description="折扣详情: {discount_type, discount_value, discount_fen, current_margin, margin_floor}",
    )
    reason: str
    requester_id: str = ""
    store_id: Optional[str] = None


class ApproveReq(BaseModel):
    approver_id: str


class RejectReq(BaseModel):
    approver_id: str
    reason: str = ""


# ─── 端点 ───


@router.post("")
async def create_approval(
    req: CreateApprovalReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """POST /api/v1/approvals — 创建审批单"""
    tenant_id = _get_tenant_id(request)
    svc = ApprovalService(db, tenant_id, req.store_id or "")

    try:
        result = await svc.create_approval(
            order_id=req.order_id,
            discount_info=req.discount_info,
            reason=req.reason,
            requester_id=req.requester_id,
            store_id=req.store_id,
        )
        return _ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{approval_id}/approve")
async def approve(
    approval_id: str,
    req: ApproveReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """PUT /api/v1/approvals/{id}/approve — 批准"""
    tenant_id = _get_tenant_id(request)
    svc = ApprovalService(db, tenant_id)

    try:
        result = await svc.approve(
            approval_id=approval_id,
            approver_id=req.approver_id,
        )
        return _ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{approval_id}/reject")
async def reject(
    approval_id: str,
    req: RejectReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """PUT /api/v1/approvals/{id}/reject — 拒绝"""
    tenant_id = _get_tenant_id(request)
    svc = ApprovalService(db, tenant_id)

    try:
        result = await svc.reject(
            approval_id=approval_id,
            approver_id=req.approver_id,
            reason=req.reason,
        )
        return _ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
async def list_approvals(
    request: Request,
    status: Optional[str] = Query(None, pattern="^(pending|approved|rejected|expired|cancelled)$"),
    store_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """GET /api/v1/approvals — 审批列表"""
    tenant_id = _get_tenant_id(request)
    svc = ApprovalService(db, tenant_id)

    result = await svc.list_approvals(
        status=status,
        store_id=store_id,
        page=page,
        size=size,
    )
    return _ok(result)


@router.get("/{approval_id}")
async def get_approval(
    approval_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """GET /api/v1/approvals/{id} — 审批详情"""
    tenant_id = _get_tenant_id(request)
    svc = ApprovalService(db, tenant_id)

    result = await svc.get_approval(approval_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Approval not found: {approval_id}")
    return _ok(result)
