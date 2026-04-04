"""供应链移动端 API Routes"""

from decimal import Decimal
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.supply_chain_mobile_service import (
    PurchaseOrderNotFoundError,
    StocktakeAlreadyCompletedError,
    StocktakeSessionNotFoundError,
    approve_purchase,
    complete_stocktake,
    confirm_receiving,
    create_receiving_order,
    get_pending_approvals,
    get_receiving_history,
    get_stocktake_report,
    record_count,
    start_stocktake,
)

router = APIRouter(prefix="/api/v1/supply", tags=["supply-chain-mobile"])
log = structlog.get_logger(__name__)


class ReceivingItemIn(BaseModel):
    ingredient_id: Optional[str] = None
    ingredient_name: str
    unit: Optional[str] = None
    ordered_qty: Optional[Decimal] = None
    received_qty: Optional[Decimal] = None
    unit_price: Optional[Decimal] = None
    discrepancy_note: Optional[str] = None


class CreateReceivingIn(BaseModel):
    store_id: str
    supplier_name: str
    items: list[ReceivingItemIn]
    receiver_id: Optional[str] = None
    notes: Optional[str] = None
    photo_urls: Optional[list[str]] = Field(default_factory=list)


@router.post("/receiving")
async def api_create_receiving(
    body: CreateReceivingIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    items_dicts = [i.model_dump() for i in body.items]
    result = await create_receiving_order(
        store_id=body.store_id,
        supplier_name=body.supplier_name,
        items=items_dicts,
        tenant_id=x_tenant_id,
        db=db,
        receiver_id=body.receiver_id,
        notes=body.notes,
    )
    confirmed = await confirm_receiving(
        order_id=result["order_id"],
        received_items=items_dicts,
        tenant_id=x_tenant_id,
        db=db,
        photo_urls=body.photo_urls,
    )
    return {"ok": True, "data": confirmed}


@router.get("/receiving/history")
async def api_receiving_history(
    store_id: str = Query(..., description="门店 ID"),
    days: int = Query(7, ge=1, le=90),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    history = await get_receiving_history(store_id=store_id, tenant_id=x_tenant_id, db=db, days=days)
    return {"ok": True, "data": history}


class StartStocktakeIn(BaseModel):
    store_id: str
    category: Optional[str] = None
    initiated_by: Optional[str] = None


@router.post("/stocktake/start")
async def api_start_stocktake(
    body: StartStocktakeIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    result = await start_stocktake(
        store_id=body.store_id,
        tenant_id=x_tenant_id,
        db=db,
        category=body.category,
        initiated_by=body.initiated_by,
    )
    return {"ok": True, "data": result}


class RecordCountIn(BaseModel):
    ingredient_id: Optional[str] = None
    ingredient_name: str
    actual_qty: Decimal
    unit: Optional[str] = None
    counted_by: Optional[str] = None
    system_qty: Optional[Decimal] = None
    unit_cost: Optional[Decimal] = None


@router.post("/stocktake/{session_id}/count")
async def api_record_count(
    session_id: str,
    body: RecordCountIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await record_count(
            session_id=session_id,
            ingredient_name=body.ingredient_name,
            actual_qty=body.actual_qty,
            tenant_id=x_tenant_id,
            db=db,
            ingredient_id=body.ingredient_id,
            unit=body.unit,
            counted_by=body.counted_by,
            system_qty=body.system_qty,
            unit_cost=body.unit_cost,
        )
    except StocktakeSessionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except StocktakeAlreadyCompletedError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"ok": True, "data": result}


@router.post("/stocktake/{session_id}/complete")
async def api_complete_stocktake(
    session_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    try:
        report = await complete_stocktake(session_id=session_id, tenant_id=x_tenant_id, db=db)
    except StocktakeSessionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except StocktakeAlreadyCompletedError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"ok": True, "data": report}


@router.get("/stocktake/{session_id}/report")
async def api_stocktake_report(
    session_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    report = await get_stocktake_report(session_id=session_id, tenant_id=x_tenant_id, db=db)
    return {"ok": True, "data": report}


@router.get("/purchase/pending-approvals")
async def api_pending_approvals(
    store_id: str = Query(..., description="门店 ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_staff_id: str = Header(..., alias="X-Staff-ID"),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await get_pending_approvals(
            approver_id=x_staff_id, store_id=store_id, tenant_id=x_tenant_id, db=db
        )
    except Exception as e:  # noqa: BLE001 — MLPS3-P0: 审批列表获取失败降级为空，最外层兜底
        log.warning("pending_approvals_fallback", error=str(e))
        result = []
    return {"ok": True, "data": result}


class ApproveIn(BaseModel):
    approved: bool
    comment: Optional[str] = None


@router.post("/purchase/{purchase_id}/approve")
async def api_approve_purchase(
    purchase_id: str,
    body: ApproveIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_staff_id: str = Header(..., alias="X-Staff-ID"),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await approve_purchase(
            purchase_id=purchase_id,
            approved=body.approved,
            approver_id=x_staff_id,
            tenant_id=x_tenant_id,
            db=db,
            comment=body.comment,
        )
    except PurchaseOrderNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True, "data": result}
