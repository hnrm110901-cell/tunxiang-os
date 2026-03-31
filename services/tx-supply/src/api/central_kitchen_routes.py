"""中央厨房完整链路 API 路由

生产计划->加工任务->配送路由->门店签收

# ROUTER REGISTRATION:
# from .api.central_kitchen_routes import router as ck_router
# app.include_router(ck_router, prefix="/api/v1/ck")
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/ck", tags=["central_kitchen"])


# ─── DB 依赖占位（由 main.py 覆盖） ───


async def _get_db():
    """数据库会话依赖 — 由 main.py 覆盖"""
    raise NotImplementedError("DB session dependency not configured")


# ─── 请求模型 ───


class GeneratePlanRequest(BaseModel):
    kitchen_id: str
    plan_date: str = Field(..., description="生产日期，格式 YYYY-MM-DD")
    store_ids: List[str] = Field(..., min_length=1, description="参与汇总需求的门店 ID 列表")
    created_by: Optional[str] = None
    capacity_kg: float = Field(5000.0, gt=0, description="中央厨房产能上限（kg）")


class CompleteTaskRequest(BaseModel):
    actual_qty: float = Field(..., ge=0, description="实际产量")


class DispatchRequest(BaseModel):
    driver_name: Optional[str] = None
    vehicle_plate: Optional[str] = None


class SignReceiptRequest(BaseModel):
    actual_qty: float = Field(..., ge=0, description="实收数量")
    operator_id: str = Field(..., description="签收操作人 ID")


# ─── 端点 ───


@router.post("/plans/generate")
async def generate_plan(
    body: GeneratePlanRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> Dict[str, Any]:
    """根据各门店次日需求量生成生产计划"""
    from ..services.production_plan_service import ProductionPlanService

    svc = ProductionPlanService()
    try:
        result = await svc.generate_plan(
            kitchen_id=body.kitchen_id,
            plan_date=body.plan_date,
            tenant_id=x_tenant_id,
            store_ids=body.store_ids,
            db=db,
            created_by=body.created_by,
            capacity_kg=body.capacity_kg,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/plans")
async def list_plans(
    kitchen_id: str = Query(..., description="中央厨房 ID"),
    date: Optional[str] = Query(None, description="过滤日期 YYYY-MM-DD"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> Dict[str, Any]:
    """查询生产计划列表"""
    from ..services.production_plan_service import ProductionPlanService

    svc = ProductionPlanService()
    try:
        results = await svc.list_plans(
            kitchen_id=kitchen_id,
            plan_date=date,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": results}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/plans/{plan_id}/confirm")
async def confirm_plan(
    plan_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> Dict[str, Any]:
    """确认生产计划，锁定所有生产任务"""
    from ..services.production_plan_service import ProductionPlanService

    svc = ProductionPlanService()
    try:
        result = await svc.confirm_plan(plan_id=plan_id, tenant_id=x_tenant_id, db=db)
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/tasks/{task_id}/complete")
async def complete_task(
    task_id: str,
    body: CompleteTaskRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> Dict[str, Any]:
    """标记加工任务完成，记录实际产量"""
    from ..services.production_plan_service import ProductionPlanService

    svc = ProductionPlanService()
    try:
        result = await svc.complete_task(
            task_id=task_id,
            actual_qty=body.actual_qty,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/plans/{plan_id}/dispatch")
async def dispatch_trips(
    plan_id: str,
    body: DispatchRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> Dict[str, Any]:
    """生产完成后生成配送任务（按地理聚类分组优化路线）"""
    from ..services.production_plan_service import ProductionPlanService

    svc = ProductionPlanService()
    try:
        trips = await svc.generate_delivery_trips(
            plan_id=plan_id, tenant_id=x_tenant_id, db=db,
        )
        return {"ok": True, "data": {"trips": trips, "trip_count": len(trips)}}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/trips/{trip_id}")
async def get_trip(
    trip_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> Dict[str, Any]:
    """查询配送单详情（含路线顺序和配送明细）"""
    from ..services.production_plan_service import ProductionPlanService

    svc = ProductionPlanService()
    try:
        result = await svc.get_trip(trip_id=trip_id, tenant_id=x_tenant_id, db=db)
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/deliveries/{item_id}/sign")
async def sign_delivery_item(
    item_id: str,
    body: SignReceiptRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> Dict[str, Any]:
    """门店签收：记录实收量，差异超 5% 自动标记 disputed"""
    from ..services.delivery_route_service import DeliveryRouteService

    svc = DeliveryRouteService()
    try:
        result = await svc.sign_receipt(
            delivery_item_id=item_id,
            actual_qty=body.actual_qty,
            operator_id=body.operator_id,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/plans/{plan_id}/variance-report")
async def get_variance_report(
    plan_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> Dict[str, Any]:
    """生成差异报告：实收 vs 计划，汇总 disputed 记录"""
    from ..services.production_plan_service import ProductionPlanService

    svc = ProductionPlanService()
    try:
        report = await svc.get_variance_report(
            plan_id=plan_id, tenant_id=x_tenant_id, db=db,
        )
        return {"ok": True, "data": report}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
