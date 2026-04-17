"""
D10 换班审批 API — Should-Fix P1

端点：
  POST /api/v1/shift-swap/request
  POST /api/v1/shift-swap/approve
  POST /api/v1/shift-swap/reject
  POST /api/v1/shift-swap/withdraw
  GET  /api/v1/shift-swap/list?store_id=
  GET  /api/v1/shift-swap/my-requests?employee_id=
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..services.shift_swap_service import shift_swap_service

router = APIRouter(prefix="/shift-swap", tags=["shift-swap"])


class RequestSwapReq(BaseModel):
    requester_id: str
    target_employee_id: str
    original_shift_id: str
    swap_shift_id: str
    reason: Optional[str] = None


class ApproveReq(BaseModel):
    req_id: str
    approver_id: str


class RejectReq(BaseModel):
    req_id: str
    approver_id: str
    reason: str = Field(..., min_length=1)


class WithdrawReq(BaseModel):
    req_id: str
    requester_id: str


def _serialize(r) -> Dict[str, Any]:
    return {
        "id": str(r.id),
        "requester_id": r.requester_id,
        "target_employee_id": r.target_employee_id,
        "original_shift_id": str(r.original_shift_id),
        "swap_shift_id": str(r.swap_shift_id),
        "reason": r.reason,
        "status": r.status,
        "approver_id": r.approver_id,
        "approved_at": r.approved_at.isoformat() if r.approved_at else None,
        "reject_reason": r.reject_reason,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.post("/request")
async def request_swap(req: RequestSwapReq, db: AsyncSession = Depends(get_db)):
    try:
        r = await shift_swap_service.request_swap(
            requester_id=req.requester_id,
            target_employee_id=req.target_employee_id,
            original_shift_id=req.original_shift_id,
            swap_shift_id=req.swap_shift_id,
            reason=req.reason,
            db=db,
        )
        return _serialize(r)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/approve")
async def approve(req: ApproveReq, db: AsyncSession = Depends(get_db)):
    try:
        r = await shift_swap_service.approve_swap(
            req_id=req.req_id, approver_id=req.approver_id, db=db
        )
        return _serialize(r)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/reject")
async def reject(req: RejectReq, db: AsyncSession = Depends(get_db)):
    try:
        r = await shift_swap_service.reject_swap(
            req_id=req.req_id, approver_id=req.approver_id, reason=req.reason, db=db
        )
        return _serialize(r)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/withdraw")
async def withdraw(req: WithdrawReq, db: AsyncSession = Depends(get_db)):
    try:
        r = await shift_swap_service.withdraw(
            req_id=req.req_id, requester_id=req.requester_id, db=db
        )
        return _serialize(r)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/list")
async def list_pending(
    store_id: str = Query(..., description="门店 ID"),
    db: AsyncSession = Depends(get_db),
):
    rows = await shift_swap_service.list_pending(store_id=store_id, db=db)
    return {"items": [_serialize(r) for r in rows], "total": len(rows)}


@router.get("/my-requests")
async def my_requests(
    employee_id: str = Query(..., description="员工 ID"),
    db: AsyncSession = Depends(get_db),
):
    rows = await shift_swap_service.list_my_requests(employee_id=employee_id, db=db)
    return {"items": [_serialize(r) for r in rows], "total": len(rows)}
