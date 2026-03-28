"""中央仓配送调度 API

5 个端点：创建配送计划、路线优化、派车、门店签收、配送看板。
"""
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from services.tx_supply.src.services import distribution

router = APIRouter(prefix="/api/v1/supply/distribution", tags=["distribution"])


# ─── Pydantic 请求体 ───


class CreatePlanRequest(BaseModel):
    warehouse_id: str
    store_orders: list[dict] = Field(
        description="[{store_id, items: [{item_id, item_name, quantity, unit}]}]",
    )


class DispatchRequest(BaseModel):
    driver_id: str


class ConfirmDeliveryRequest(BaseModel):
    store_id: str
    received_items: list[dict] = Field(
        description="[{item_id, received_quantity, status: accepted|rejected|partial, notes}]",
    )


# ─── 端点 ───


@router.post("/plan")
async def create_distribution_plan(
    body: CreatePlanRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
):
    """创建配送计划"""
    result = distribution.create_distribution_plan(
        warehouse_id=body.warehouse_id,
        store_orders=body.store_orders,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}


@router.post("/plan/{plan_id}/optimize")
async def optimize_route(
    plan_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
):
    """路线优化（按门店距离排序）"""
    try:
        result = distribution.optimize_route(
            plan_id=plan_id,
            tenant_id=x_tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True, "data": result}


@router.post("/plan/{plan_id}/dispatch")
async def dispatch_delivery(
    plan_id: str,
    body: DispatchRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
):
    """派车"""
    try:
        result = distribution.dispatch_delivery(
            plan_id=plan_id,
            driver_id=body.driver_id,
            tenant_id=x_tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"ok": True, "data": result}


@router.post("/plan/{plan_id}/confirm")
async def confirm_delivery(
    plan_id: str,
    body: ConfirmDeliveryRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
):
    """门店签收"""
    try:
        result = distribution.confirm_delivery(
            plan_id=plan_id,
            store_id=body.store_id,
            received_items=body.received_items,
            tenant_id=x_tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"ok": True, "data": result}


@router.get("/dashboard/{warehouse_id}")
async def get_distribution_dashboard(
    warehouse_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
):
    """配送看板"""
    result = distribution.get_distribution_dashboard(
        warehouse_id=warehouse_id,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}
