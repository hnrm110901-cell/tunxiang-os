"""高峰值守 API 路由 — E3 模块

5 个端点: 高峰检测/档口负载/服务加派/等位拥堵/事件处理
统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/peak", tags=["peak-management"])


# ─── 请求模型 ───


class HandlePeakEventRequest(BaseModel):
    event_type: str  # temp_menu_switch / table_merge / table_split / express_mode / queue_divert
    params: Optional[dict] = None


# ─── 依赖 ───


def _get_tenant_id(x_tenant_id: str = Header(...)) -> str:
    return x_tenant_id


# ─── 1. 高峰检测 ───


@router.get("/stores/{store_id}/detect")
async def detect_peak(
    store_id: str,
    x_tenant_id: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """检测是否进入高峰（基于当前上座率 + 等位数）"""
    from ..services.peak_management import detect_peak as svc

    try:
        result = await svc(store_id=store_id, tenant_id=x_tenant_id, db=db)
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── 2. 档口负载实时监控 ───


@router.get("/stores/{store_id}/dept-load")
async def get_dept_load_monitor(
    store_id: str,
    x_tenant_id: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """档口负载实时监控"""
    from ..services.peak_management import get_dept_load_monitor as svc

    try:
        result = await svc(store_id=store_id, tenant_id=x_tenant_id, db=db)
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── 3. 服务加派建议 ───


@router.get("/stores/{store_id}/staff-dispatch")
async def suggest_staff_dispatch(
    store_id: str,
    x_tenant_id: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """服务加派建议"""
    from ..services.peak_management import suggest_staff_dispatch as svc

    try:
        result = await svc(store_id=store_id, tenant_id=x_tenant_id, db=db)
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── 4. 等位拥堵指标 ───


@router.get("/stores/{store_id}/queue-pressure")
async def get_queue_pressure(
    store_id: str,
    x_tenant_id: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """等位拥堵指标"""
    from ..services.peak_management import get_queue_pressure as svc

    try:
        result = await svc(store_id=store_id, tenant_id=x_tenant_id, db=db)
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── 5. 高峰事件处理 ───


@router.post("/stores/{store_id}/events")
async def handle_peak_event(
    store_id: str,
    body: HandlePeakEventRequest,
    x_tenant_id: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """高峰事件处理（临时调菜/调台/快速出餐/分流）"""
    from ..services.peak_management import handle_peak_event as svc

    try:
        result = await svc(
            store_id=store_id,
            event_type=body.event_type,
            tenant_id=x_tenant_id,
            db=db,
            params=body.params,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
