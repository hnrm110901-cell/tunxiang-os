"""KDS 缺料联动 API -- 缺料上报联动/出品节拍/出品顺序优化

所有接口需要 X-Tenant-ID header。
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.kds_shortage_link import (
    get_production_rhythm,
    on_shortage_reported,
    optimize_production_sequence,
)

router = APIRouter(prefix="/api/v1/kds/shortage", tags=["kds-shortage"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


# ─── 请求模型 ───


class ShortageReportRequest(BaseModel):
    task_id: str
    ingredient_id: str
    store_id: str


class ProductionRhythmRequest(BaseModel):
    store_id: str
    start_date: date
    end_date: date


class OptimizeSequenceRequest(BaseModel):
    dept_id: str
    store_id: str = ""


# ─── 端点 ───


@router.post("/report")
async def api_on_shortage_reported(
    body: ShortageReportRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """缺料上报联动 -- 自动验证库存/沽清/通知/采购建议"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await on_shortage_reported(
            task_id=body.task_id,
            ingredient_id=body.ingredient_id,
            store_id=body.store_id,
            tenant_id=tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rhythm")
async def api_get_production_rhythm(
    body: ProductionRhythmRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """出品节拍分析（各档口出品速度/瓶颈）"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await get_production_rhythm(
            store_id=body.store_id,
            date_range=(body.start_date, body.end_date),
            tenant_id=tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/optimize")
async def api_optimize_production_sequence(
    body: OptimizeSequenceRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """优化出品顺序（减少等待）"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await optimize_production_sequence(
            dept_id=body.dept_id,
            tenant_id=tenant_id,
            db=db,
            store_id=body.store_id,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
