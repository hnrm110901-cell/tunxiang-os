"""中央仓配送调度 API — 已迁移到 DB（v096）

5 个业务端点 + 3 个数据注入端点：
  POST   /api/v1/supply/distribution/plan
  POST   /api/v1/supply/distribution/plan/{plan_id}/optimize
  POST   /api/v1/supply/distribution/plan/{plan_id}/dispatch
  POST   /api/v1/supply/distribution/plan/{plan_id}/confirm
  GET    /api/v1/supply/distribution/dashboard/{warehouse_id}

  POST   /api/v1/supply/distribution/warehouses/{warehouse_id}
  POST   /api/v1/supply/distribution/stores/{store_id}/geo
  POST   /api/v1/supply/distribution/drivers/{driver_id}
"""
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from services.tx_supply.src.services import distribution
from shared.ontology.src.database import get_db
from ..services.distribution_repository import DistributionRepository

router = APIRouter(prefix="/api/v1/supply/distribution", tags=["distribution"])


def _repo(db: AsyncSession, tenant_id: str) -> DistributionRepository:
    return DistributionRepository(db=db, tenant_id=tenant_id)


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


class WarehouseDataRequest(BaseModel):
    warehouse_name: str
    lat: float
    lng: float
    address: str | None = None
    capacity_kg: float | None = None


class StoreGeoRequest(BaseModel):
    store_name: str = ""
    lat: float
    lng: float
    address: str | None = None


class DriverDataRequest(BaseModel):
    driver_name: str
    phone: str | None = None
    vehicle_no: str | None = None
    vehicle_type: str | None = None
    capacity_kg: float | None = None


# ─── 业务端点 ───


@router.post("/plan")
async def create_distribution_plan(
    body: CreatePlanRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """创建配送计划"""
    result = await distribution.create_distribution_plan(
        warehouse_id=body.warehouse_id,
        store_orders=body.store_orders,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": result}


@router.post("/plan/{plan_id}/optimize")
async def optimize_route(
    plan_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """路线优化（按门店距离排序）"""
    try:
        result = await distribution.optimize_route(
            plan_id=plan_id,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/plan/{plan_id}/dispatch")
async def dispatch_delivery(
    plan_id: str,
    body: DispatchRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """派车"""
    try:
        result = await distribution.dispatch_delivery(
            plan_id=plan_id,
            driver_id=body.driver_id,
            tenant_id=x_tenant_id,
            db=db,
        )
        await db.commit()
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/plan/{plan_id}/confirm")
async def confirm_delivery(
    plan_id: str,
    body: ConfirmDeliveryRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """门店签收"""
    try:
        result = await distribution.confirm_delivery(
            plan_id=plan_id,
            store_id=body.store_id,
            received_items=body.received_items,
            tenant_id=x_tenant_id,
            db=db,
        )
        await db.commit()
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/dashboard/{warehouse_id}")
async def get_distribution_dashboard(
    warehouse_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """配送看板"""
    result = await distribution.get_distribution_dashboard(
        warehouse_id=warehouse_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": result}


# ─── 数据注入端点（仓库/门店地理/司机）───


@router.post("/warehouses/{warehouse_id}")
async def inject_warehouse(
    warehouse_id: str,
    body: WarehouseDataRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """注入/更新仓库信息"""
    repo = _repo(db, x_tenant_id)
    await repo.upsert_warehouse(warehouse_id, body.model_dump())
    await db.commit()
    return {"ok": True}


@router.post("/stores/{store_id}/geo")
async def inject_store_geo(
    store_id: str,
    body: StoreGeoRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """注入/更新门店地理信息"""
    repo = _repo(db, x_tenant_id)
    await repo.upsert_store_geo(store_id, body.model_dump())
    await db.commit()
    return {"ok": True}


@router.post("/drivers/{driver_id}")
async def inject_driver(
    driver_id: str,
    body: DriverDataRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """注入/更新司机信息"""
    repo = _repo(db, x_tenant_id)
    await repo.upsert_driver(driver_id, body.model_dump())
    await db.commit()
    return {"ok": True}
