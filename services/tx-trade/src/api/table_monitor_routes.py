"""桌台监控 API — 前厅大屏数据接口

ROUTER REGISTRATION:
# from .api.table_monitor_routes import router as table_monitor_router
# app.include_router(table_monitor_router, prefix="/api/v1/table-monitor")

所有接口需要 X-Tenant-ID header。
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..services.table_monitor_service import TableMonitorService

router = APIRouter(prefix="/api/v1/table-monitor", tags=["table-monitor"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


@router.get("/overview/{store_id}")
async def api_store_overview(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """全店桌台状态汇总 — 前厅监控大屏主接口

    返回该门店所有有活跃任务的桌台及其当前状态，包含：
    - 进行中菜品数 / 已出菜数
    - 起菜时长（elapsed_minutes）
    - 是否超时（is_overtime）
    - 催单次数（rush_count）
    - 待出菜品摘要列表
    """
    tenant_id = _get_tenant_id(request)
    try:
        tables = await TableMonitorService.get_store_overview(store_id, tenant_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "data": {"tables": [t.model_dump() for t in tables], "total": len(tables)}}


@router.get("/table/{table_id}")
async def api_table_detail(
    table_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """单桌菜品级别详情

    返回该桌所有菜品（含已出品）的状态、用时、催单次数等。
    """
    tenant_id = _get_tenant_id(request)
    try:
        detail = await TableMonitorService.get_table_detail(table_id, tenant_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if detail is None:
        raise HTTPException(status_code=404, detail=f"桌台 {table_id} 无活跃订单")
    return {"ok": True, "data": detail.model_dump()}


@router.get("/zones/{store_id}")
async def api_zone_summary(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """按区域（包厢/大厅）分组汇总

    返回每个区域的桌台数、超时数、催单数、平均起菜时长。
    """
    tenant_id = _get_tenant_id(request)
    try:
        summary = await TableMonitorService.get_zone_summary(store_id, tenant_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "data": {zone: s.model_dump() for zone, s in summary.items()},
    }


@router.get("/alerts/{store_id}")
async def api_alerts(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """当前超时 + 催单桌台列表

    仅返回 is_overtime=True 或 rush_count>0 的桌台，用于告警面板。
    """
    tenant_id = _get_tenant_id(request)
    try:
        alerts = await TableMonitorService.get_alerts(store_id, tenant_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "data": {
            "alerts": [a.model_dump() for a in alerts],
            "total": len(alerts),
            "overtime": len([a for a in alerts if a.is_overtime]),
            "rush": len([a for a in alerts if a.rush_count > 0 and not a.is_overtime]),
        },
    }
