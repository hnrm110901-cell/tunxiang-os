"""
D10 多打卡方式 API — Should-Fix P1

端点：
  POST /api/v1/attendance-punch/punch-in
  POST /api/v1/attendance-punch/punch-out
  GET  /api/v1/attendance-punch/list
  POST /api/v1/attendance-punch/verify-gps  # 纯验证工具
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..models.attendance_punch import PunchMethod
from ..services.attendance_punch_service import attendance_punch_service

router = APIRouter(prefix="/attendance-punch", tags=["attendance-punch"])


class PunchRequest(BaseModel):
    employee_id: str
    store_id: str
    method: PunchMethod
    payload: Dict[str, Any] = Field(default_factory=dict)
    shift_id: Optional[str] = None


class VerifyGpsRequest(BaseModel):
    employee_lat: float
    employee_lng: float
    store_lat: float
    store_lng: float
    radius_meters: int = 200


def _serialize(p) -> Dict[str, Any]:
    return {
        "id": str(p.id),
        "employee_id": p.employee_id,
        "store_id": p.store_id,
        "punch_at": p.punch_at.isoformat() if p.punch_at else None,
        "direction": p.direction,
        "method": p.method,
        "verified": p.verified,
        "verify_remark": p.verify_remark,
        "needs_approval": p.needs_approval,
        "shift_id": str(p.shift_id) if p.shift_id else None,
    }


@router.post("/punch-in")
async def punch_in(req: PunchRequest, db: AsyncSession = Depends(get_db)):
    try:
        p = await attendance_punch_service.punch_in(
            employee_id=req.employee_id,
            store_id=req.store_id,
            method=req.method,
            payload=req.payload,
            db=db,
            shift_id=req.shift_id,
        )
        return _serialize(p)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/punch-out")
async def punch_out(req: PunchRequest, db: AsyncSession = Depends(get_db)):
    try:
        p = await attendance_punch_service.punch_out(
            employee_id=req.employee_id,
            store_id=req.store_id,
            method=req.method,
            payload=req.payload,
            db=db,
            shift_id=req.shift_id,
        )
        return _serialize(p)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/list")
async def list_punches(
    employee_id: Optional[str] = Query(None),
    store_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    rows = await attendance_punch_service.list_punches(
        employee_id=employee_id, store_id=store_id, db=db, limit=limit
    )
    return {"items": [_serialize(r) for r in rows], "total": len(rows)}


@router.post("/verify-gps")
async def verify_gps(req: VerifyGpsRequest):
    """纯函数 GPS 校验工具（不落库）"""
    return attendance_punch_service.verify_gps(
        employee_lat=req.employee_lat,
        employee_lng=req.employee_lng,
        store_lat=req.store_lat,
        store_lng=req.store_lng,
        radius_meters=req.radius_meters,
    )
