"""OrderHub API — cross-platform unified order queries."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.order_hub import OrderHub, OrderHubFilters

router = APIRouter(prefix="/api/v1/orders", tags=["order-hub"])


def _tid(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID required")
    return tid


@router.get("")
async def list_orders(
    request: Request,
    platform: str = Query(""),
    status: str = Query(""),
    store_id: str = Query(""),
    keyword: str = Query(""),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    hub = OrderHub(db, _tid(request))
    filters = OrderHubFilters(
        platform=platform, status=status, store_id=store_id,
        keyword=keyword, page=page, size=size,
    )
    return {"ok": True, "data": await hub.list_orders(filters)}


@router.get("/stats")
async def order_stats(
    request: Request,
    store_id: str = Query(""),
    platform: str = Query(""),
    db: AsyncSession = Depends(get_db),
):
    hub = OrderHub(db, _tid(request))
    return {"ok": True, "data": await hub.get_stats(store_id=store_id, platform=platform)}


@router.get("/{order_id}")
async def order_detail(
    order_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    hub = OrderHub(db, _tid(request))
    detail = await hub.get_order_detail(order_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Order not found")
    return {"ok": True, "data": detail}
