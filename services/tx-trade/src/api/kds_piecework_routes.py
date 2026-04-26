"""KDS计件配菜 API — 计件记录 + 员工汇总 + 门店日报 + 佣金计算 + 方案CRUD

所有接口需要 X-Tenant-ID header。
ROUTER REGISTRATION（在 main.py 中添加）：
  from .api.kds_piecework_routes import router as kds_piecework_router
  app.include_router(kds_piecework_router, prefix="/api/v1/kds-piecework")
"""

from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.kds_piecework_service import KdsPieceworkService

logger = structlog.get_logger()

router = APIRouter(tags=["kds-piecework"])


# ── 公共依赖 ─────────────────────────────────────────────────

def _tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


# ── 请求/响应模型 ────────────────────────────────────────────

class RecordPieceworkRequest(BaseModel):
    store_id: str
    employee_id: str
    shift_date: date
    dish_id: Optional[str] = None
    dish_name: Optional[str] = None
    practice_names: Optional[str] = None
    quantity: int = 1
    unit_commission_fen: int = 0
    confirmed_by: str = "auto"
    kds_task_id: Optional[str] = None


class CreateSchemeRequest(BaseModel):
    store_id: Optional[str] = None
    scheme_name: str
    scheme_type: str = Field(..., pattern="^(by_dish|by_practice|by_station)$")
    rules: list = Field(default_factory=list)
    effective_from: date
    effective_until: Optional[date] = None


class UpdateSchemeRequest(BaseModel):
    scheme_name: Optional[str] = None
    is_active: Optional[bool] = None
    rules: Optional[list] = None
    effective_until: Optional[date] = None


# ── 端点 ─────────────────────────────────────────────────────

@router.post("/record")
async def record_piecework(
    body: RecordPieceworkRequest,
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """记录一条计件数据（kds_task_id 幂等）"""
    result = await KdsPieceworkService.record_piecework(
        db,
        tenant_id,
        store_id=body.store_id,
        employee_id=body.employee_id,
        shift_date=body.shift_date,
        dish_id=body.dish_id,
        dish_name=body.dish_name,
        practice_names=body.practice_names,
        quantity=body.quantity,
        unit_commission_fen=body.unit_commission_fen,
        confirmed_by=body.confirmed_by,
        kds_task_id=body.kds_task_id,
    )
    return {"ok": True, "data": result}


@router.get("/summary")
async def get_employee_summary(
    store_id: str = Query(...),
    employee_id: str = Query(...),
    start_date: date = Query(...),
    end_date: date = Query(...),
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """获取员工计件汇总"""
    result = await KdsPieceworkService.get_employee_summary(
        db,
        tenant_id,
        store_id=store_id,
        employee_id=employee_id,
        start_date=start_date,
        end_date=end_date,
    )
    return {"ok": True, "data": result}


@router.get("/daily")
async def get_store_daily(
    store_id: str = Query(...),
    shift_date: date = Query(...),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """获取门店某日的全员计件明细"""
    result = await KdsPieceworkService.get_store_daily(
        db,
        tenant_id,
        store_id=store_id,
        shift_date=shift_date,
        page=page,
        size=size,
    )
    return {"ok": True, "data": result}


@router.get("/calculate-commission")
async def calculate_commission(
    store_id: str = Query(...),
    employee_id: str = Query(...),
    shift_date: date = Query(...),
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """计算员工当日佣金"""
    result = await KdsPieceworkService.calculate_commission(
        db,
        tenant_id,
        store_id=store_id,
        employee_id=employee_id,
        shift_date=shift_date,
    )
    return {"ok": True, "data": result}


@router.post("/schemes")
async def create_scheme(
    body: CreateSchemeRequest,
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """创建计件方案"""
    result = await KdsPieceworkService.create_scheme(
        db,
        tenant_id,
        store_id=body.store_id,
        scheme_name=body.scheme_name,
        scheme_type=body.scheme_type,
        rules=body.rules,
        effective_from=body.effective_from,
        effective_until=body.effective_until,
    )
    return {"ok": True, "data": result}


@router.get("/schemes")
async def list_schemes(
    store_id: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """列出计件方案"""
    result = await KdsPieceworkService.list_schemes(
        db,
        tenant_id,
        store_id=store_id,
        is_active=is_active,
        page=page,
        size=size,
    )
    return {"ok": True, "data": result}


@router.put("/schemes/{scheme_id}")
async def update_scheme(
    scheme_id: str,
    body: UpdateSchemeRequest,
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """更新计件方案"""
    result = await KdsPieceworkService.update_scheme(
        db,
        tenant_id,
        scheme_id=scheme_id,
        scheme_name=body.scheme_name,
        is_active=body.is_active,
        rules=body.rules,
        effective_until=body.effective_until,
    )
    return {"ok": True, "data": result}


@router.delete("/schemes/{scheme_id}")
async def delete_scheme(
    scheme_id: str,
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """删除计件方案"""
    result = await KdsPieceworkService.delete_scheme(db, tenant_id, scheme_id)
    return {"ok": True, "data": result}
