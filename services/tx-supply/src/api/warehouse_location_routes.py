"""库位/库区/温区 API — TASK-2 仓储库存细化

端点（11 个）：
  POST   /api/v1/supply/warehouse/zones
  GET    /api/v1/supply/warehouse/zones
  PATCH  /api/v1/supply/warehouse/zones/{id}
  GET    /api/v1/supply/warehouse/zones/{id}/utilization

  POST   /api/v1/supply/warehouse/locations
  GET    /api/v1/supply/warehouse/locations
  GET    /api/v1/supply/warehouse/locations/abc-suggestion?store_id=
  POST   /api/v1/supply/warehouse/locations/auto-allocate
  POST   /api/v1/supply/warehouse/locations/move
  POST   /api/v1/supply/warehouse/locations/{id}/bind-ingredient

  GET    /api/v1/supply/warehouse/inventory/by-location?store_id=&zone_id=
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db as _get_db

from ..models.warehouse_location import (
    AutoAllocateRequest,
    BindIngredientRequest,
    LocationCreate,
    MoveBetweenLocationsRequest,
    ZoneCreate,
    ZoneUpdate,
)
from ..services import warehouse_location_service as svc
from ..services.warehouse_location_service import (
    DuplicateCodeError,
    InsufficientInventoryError,
    LocationCapacityExceededError,
    LocationNotFoundError,
    TemperatureMismatchError,
    WarehouseLocationError,
    ZoneNotFoundError,
)

router = APIRouter(prefix="/api/v1/supply/warehouse", tags=["supply-warehouse-location"])


def _err(code: str, message: str) -> dict:
    return {"ok": False, "data": None, "error": {"code": code, "message": message}}


# ─────────────────────────────────────────────────────────────────────────────
# Zones
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/zones")
async def create_zone(
    body: ZoneCreate,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    try:
        data = await svc.create_zone(body=body, tenant_id=x_tenant_id, db=db)
        return {"ok": True, "data": data, "error": None}
    except DuplicateCodeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WarehouseLocationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/zones")
async def list_zones(
    store_id: str,
    temperature_type: Optional[str] = None,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    data = await svc.list_zones(
        store_id=store_id,
        tenant_id=x_tenant_id,
        db=db,
        temperature_type=temperature_type,
    )
    return {"ok": True, "data": {"zones": data, "total": len(data)}, "error": None}


@router.patch("/zones/{zone_id}")
async def update_zone(
    zone_id: str,
    body: ZoneUpdate,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    try:
        data = await svc.update_zone(
            zone_id=zone_id, body=body, tenant_id=x_tenant_id, db=db
        )
        return {"ok": True, "data": data, "error": None}
    except ZoneNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WarehouseLocationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/zones/{zone_id}/utilization")
async def zone_utilization(
    zone_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    try:
        data = await svc.compute_zone_utilization(
            zone_id=zone_id, tenant_id=x_tenant_id, db=db
        )
        return {"ok": True, "data": data, "error": None}
    except WarehouseLocationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ─────────────────────────────────────────────────────────────────────────────
# Locations
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/locations")
async def create_location(
    body: LocationCreate,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    try:
        data = await svc.create_location(body=body, tenant_id=x_tenant_id, db=db)
        return {"ok": True, "data": data, "error": None}
    except ZoneNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DuplicateCodeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WarehouseLocationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/locations")
async def list_locations(
    store_id: Optional[str] = None,
    zone_id: Optional[str] = None,
    abc_class: Optional[str] = None,
    enabled_only: bool = True,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    data = await svc.list_locations(
        tenant_id=x_tenant_id,
        db=db,
        store_id=store_id,
        zone_id=zone_id,
        abc_class=abc_class,
        enabled_only=enabled_only,
    )
    return {"ok": True, "data": {"locations": data, "total": len(data)}, "error": None}


@router.get("/locations/abc-suggestion")
async def abc_suggestion(
    store_id: str,
    days: int = 30,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    try:
        data = await svc.suggest_abc_optimization(
            store_id=store_id, tenant_id=x_tenant_id, db=db, days=days
        )
        return {"ok": True, "data": data, "error": None}
    except WarehouseLocationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/locations/auto-allocate")
async def auto_allocate(
    body: AutoAllocateRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    try:
        data = await svc.auto_allocate_location(
            body=body, tenant_id=x_tenant_id, db=db
        )
        return {"ok": True, "data": data, "error": None}
    except TemperatureMismatchError as exc:
        return _err("temperature_mismatch", str(exc))
    except LocationCapacityExceededError as exc:
        return _err("capacity_exceeded", str(exc))
    except LocationNotFoundError as exc:
        return _err("no_location", str(exc))
    except WarehouseLocationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/locations/move")
async def move_location(
    body: MoveBetweenLocationsRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    try:
        data = await svc.move_between_locations(
            body=body, tenant_id=x_tenant_id, db=db
        )
        return {"ok": True, "data": data, "error": None}
    except InsufficientInventoryError as exc:
        return _err("insufficient_inventory", str(exc))
    except LocationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WarehouseLocationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/locations/{location_id}/bind-ingredient")
async def bind_ingredient(
    location_id: str,
    body: BindIngredientRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    try:
        data = await svc.bind_ingredient_to_location(
            location_id=location_id,
            body=body,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": data, "error": None}
    except LocationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WarehouseLocationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ─────────────────────────────────────────────────────────────────────────────
# Inventory query
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/inventory/by-location")
async def inventory_by_location(
    store_id: Optional[str] = None,
    zone_id: Optional[str] = None,
    location_id: Optional[str] = None,
    ingredient_id: Optional[str] = None,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    data = await svc.query_inventory_by_location(
        tenant_id=x_tenant_id,
        db=db,
        store_id=store_id,
        zone_id=zone_id,
        location_id=location_id,
        ingredient_id=ingredient_id,
    )
    return {"ok": True, "data": {"items": data, "total": len(data)}, "error": None}
