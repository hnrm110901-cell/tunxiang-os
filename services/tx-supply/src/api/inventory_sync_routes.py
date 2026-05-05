"""Inventory sync trigger API — manual stock push to platforms."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Query, Request

from ..services.inventory_sync_service import InventorySyncService

router = APIRouter(prefix="/api/v1/inventory-sync", tags=["inventory-sync"])


@router.post("/trigger")
async def trigger_stock_sync(
    request: Request,
    sku_id: str = Query(...),
    stock: int = Query(..., ge=0),
    store_id: str = Query(""),
    background_tasks: BackgroundTasks,
):
    """Manually trigger stock sync to all platforms.

    POST /api/v1/inventory-sync/trigger?sku_id=SKU001&stock=0
    """
    svc = InventorySyncService()
    background_tasks.add_task(svc.sync_stock_to_all_platforms, sku_id, stock, store_id)
    return {
        "ok": True,
        "data": {"sku_id": sku_id, "stock": stock, "status": "queued"},
    }
