"""供应链移动端 API Routes"""

from decimal import Decimal
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..services.supply_chain_mobile_service import (
    ReceivingOrderNotFoundError,
    StocktakeAlreadyCompletedError,
    StocktakeSessionNotFoundError,
    PurchaseOrderNotFoundError,
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

MOCK_TENANT = "00000000-0000-0000-0000-000000000001"
MOCK_STORE = "00000000-0000-0000-0000-000000000002"
MOCK_STAFF = "00000000-0000-0000-0000-000000000003"


def _tenant(tenant_id: Optional[str] = Query(None)) -> str:
    return tenant_id or MOCK_TENANT


def _store(store_id: Optional[str] = Query(None)) -> str:
    return store_id or MOCK_STORE


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
async def api_create_receiving(body: CreateReceivingIn, db: AsyncSession = Depends(get_db)):
    tenant_id = MOCK_TENANT
    items_dicts = [i.model_dump() for i in body.items]
    result = await create_receiving_order(
        store_id=body.store_id,
        supplier_name=body.supplier_name,
        items=items_dicts,
        tenant_id=tenant_id,
        db=db,
        receiver_id=body.receiver_id,
        notes=body.notes,
    )
    confirmed = await confirm_receiving(
        order_id=result["order_id"],
        received_items=items_dicts,
        tenant_id=tenant_id,
        db=db,
        photo_urls=body.photo_urls,
    )
    return {"ok": True, "data": confirmed}


@router.get("/receiving/history")
async def api_receiving_history(
    store_id: str = Query(MOCK_STORE),
    days: int = Query(7, ge=1, le=90),
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
):
    history = await get_receiving_history(store_id=store_id, tenant_id=tenant_id, db=db, days=days)
    return {"ok": True, "data": history}


class StartStocktakeIn(BaseModel):
    store_id: str
    category: Optional[str] = None
    initiated_by: Optional[str] = None


@router.post("/stocktake/start")
async def api_start_stocktake(body: StartStocktakeIn, db: AsyncSession = Depends(get_db)):
    tenant_id = MOCK_TENANT
    result = await start_stocktake(
        store_id=body.store_id,
        tenant_id=tenant_id,
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
    db: AsyncSession = Depends(get_db),
):
    tenant_id = MOCK_TENANT
    try:
        result = await record_count(
            session_id=session_id,
            ingredient_name=body.ingredient_name,
            actual_qty=body.actual_qty,
            tenant_id=tenant_id,
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
async def api_complete_stocktake(session_id: str, db: AsyncSession = Depends(get_db)):
    tenant_id = MOCK_TENANT
    try:
        report = await complete_stocktake(session_id=session_id, tenant_id=tenant_id, db=db)
    except StocktakeSessionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except StocktakeAlreadyCompletedError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"ok": True, "data": report}


@router.get("/stocktake/{session_id}/report")
async def api_stocktake_report(session_id: str, db: AsyncSession = Depends(get_db)):
    tenant_id = MOCK_TENANT
    report = await get_stocktake_report(session_id=session_id, tenant_id=tenant_id, db=db)
    return {"ok": True, "data": report}


@router.get("/purchase/pending-approvals")
async def api_pending_approvals(
    store_id: str = Query(MOCK_STORE),
    tenant_id: str = Depends(_tenant),
    db: AsyncSession = Depends(get_db),
):
    approver_id = MOCK_STAFF
    try:
        result = await get_pending_approvals(
            approver_id=approver_id, store_id=store_id, tenant_id=tenant_id, db=db
        )
    except Exception as e:
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
    db: AsyncSession = Depends(get_db),
):
    tenant_id = MOCK_TENANT
    approver_id = MOCK_STAFF
    try:
        result = await approve_purchase(
            purchase_id=purchase_id,
            approved=body.approved,
            approver_id=approver_id,
            tenant_id=tenant_id,
            db=db,
            comment=body.comment,
        )
    except PurchaseOrderNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True, "data": result}
