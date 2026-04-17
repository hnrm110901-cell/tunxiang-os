"""
D8 采购单审批流 API — Should-Fix P1

端点：
  POST /api/v1/purchase-approval/submit
  POST /api/v1/purchase-approval/approve
  POST /api/v1/purchase-approval/reject
  GET  /api/v1/purchase-approval/history/{po_id}
"""

from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..models.purchase_approval import ApprovalLevel
from ..services.purchase_approval_service import purchase_approval_service

logger = structlog.get_logger()
router = APIRouter(prefix="/purchase-approval", tags=["purchase-approval"])


class SubmitRequest(BaseModel):
    po_id: str = Field(..., description="采购单 ID")
    requester: str = Field(..., description="提交人 ID")


class ApproveRequest(BaseModel):
    po_id: str
    approver: str
    level: ApprovalLevel


class RejectRequest(BaseModel):
    po_id: str
    approver: str
    reason: str = Field(..., min_length=1)


@router.post("/submit")
async def submit(req: SubmitRequest, db: AsyncSession = Depends(get_db)):
    try:
        po = await purchase_approval_service.submit_for_approval(
            po_id=req.po_id, requester=req.requester, db=db
        )
        return {
            "po_id": po.id,
            "status": po.status,
            "total_amount_yuan": round((po.total_amount or 0) / 100, 2),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/approve")
async def approve(req: ApproveRequest, db: AsyncSession = Depends(get_db)):
    try:
        po = await purchase_approval_service.approve(
            po_id=req.po_id, approver=req.approver, level=req.level, db=db
        )
        return {"po_id": po.id, "status": po.status, "approved_by": po.approved_by}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/reject")
async def reject(req: RejectRequest, db: AsyncSession = Depends(get_db)):
    try:
        po = await purchase_approval_service.reject(
            po_id=req.po_id, approver=req.approver, reason=req.reason, db=db
        )
        return {"po_id": po.id, "status": po.status}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/history/{po_id}")
async def history(po_id: str, db: AsyncSession = Depends(get_db)):
    logs = await purchase_approval_service.get_approval_history(po_id=po_id, db=db)
    return {
        "po_id": po_id,
        "logs": [
            {
                "id": str(log.id),
                "level": log.level,
                "action": log.action,
                "approver_id": log.approver_id,
                "amount_snapshot_yuan": log.amount_snapshot_yuan,
                "reason": log.reason,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
    }
