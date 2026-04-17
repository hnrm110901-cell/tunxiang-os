"""
AR/AP 应收应付 API — D7-P0 Must-Fix Task 2

路由前缀: /api/v1/ar-ap
"""

from datetime import date
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.exceptions import NotFoundError, ValidationError
from src.services.ar_ap_service import get_ar_ap_service

router = APIRouter()


# ──────────────── Pydantic ────────────────


class CreateARRequest(BaseModel):
    customer_name: str = Field(..., description="客户名称")
    amount_fen: int = Field(..., gt=0, description="应收金额（分）")
    customer_id: Optional[UUID] = None
    customer_type: str = "credit_account"
    store_id: Optional[UUID] = None
    brand_id: Optional[UUID] = None
    source_bill_id: Optional[UUID] = None
    source_ref: Optional[str] = None
    due_date: Optional[date] = None
    remark: Optional[str] = None


class ReceiveARRequest(BaseModel):
    amount_fen: int = Field(..., gt=0)
    payment_method: str = "bank_transfer"
    payment_date: Optional[date] = None
    reference_no: Optional[str] = None
    remark: Optional[str] = None


class CreateAPRequest(BaseModel):
    supplier_name: str = Field(..., description="供应商名称")
    amount_fen: int = Field(..., gt=0)
    supplier_id: Optional[UUID] = None
    store_id: Optional[UUID] = None
    brand_id: Optional[UUID] = None
    source_po_id: Optional[UUID] = None
    source_ref: Optional[str] = None
    due_date: Optional[date] = None
    expense_account_code: str = "1405"
    remark: Optional[str] = None


class PayAPRequest(BaseModel):
    amount_fen: int = Field(..., gt=0)
    payment_method: str = "bank_transfer"
    payment_date: Optional[date] = None
    reference_no: Optional[str] = None
    remark: Optional[str] = None


# ──────────────── AR 路由 ────────────────


@router.post("/ar", summary="创建应收", response_model=Dict[str, Any])
async def create_ar(
    payload: CreateARRequest,
    db: AsyncSession = Depends(get_db),
):
    svc = get_ar_ap_service(db)
    try:
        return await svc.create_ar(**payload.model_dump(exclude_none=True))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/ar", summary="应收列表")
async def list_ar(
    store_id: Optional[UUID] = Query(None),
    status: Optional[str] = Query(None),
    customer_id: Optional[UUID] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    return await get_ar_ap_service(db).list_ar(
        store_id=store_id, status=status, customer_id=customer_id, limit=limit, offset=offset
    )


@router.get("/ar/{ar_id}", summary="应收详情")
async def get_ar(ar_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        return await get_ar_ap_service(db).get_ar(ar_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/ar/{ar_id}/receive", summary="应收收款")
async def receive_ar(
    ar_id: UUID,
    payload: ReceiveARRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await get_ar_ap_service(db).receive_ar(ar_id=ar_id, **payload.model_dump(exclude_none=True))
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ──────────────── AP 路由 ────────────────


@router.post("/ap", summary="创建应付", response_model=Dict[str, Any])
async def create_ap(
    payload: CreateAPRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await get_ar_ap_service(db).create_ap(**payload.model_dump(exclude_none=True))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/ap", summary="应付列表")
async def list_ap(
    store_id: Optional[UUID] = Query(None),
    status: Optional[str] = Query(None),
    supplier_id: Optional[UUID] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    return await get_ar_ap_service(db).list_ap(
        store_id=store_id, status=status, supplier_id=supplier_id, limit=limit, offset=offset
    )


@router.get("/ap/{ap_id}", summary="应付详情")
async def get_ap(ap_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        return await get_ar_ap_service(db).get_ap(ap_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/ap/{ap_id}/pay", summary="应付付款")
async def pay_ap(
    ap_id: UUID,
    payload: PayAPRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await get_ar_ap_service(db).pay_ap(ap_id=ap_id, **payload.model_dump(exclude_none=True))
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ──────────────── 账龄报表 ────────────────


@router.get("/aging", summary="账龄报表（0-30/31-60/61-90/90+）")
async def aging_report(
    kind: str = Query("ar", regex="^(ar|ap)$"),
    store_id: Optional[UUID] = Query(None),
    as_of: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await get_ar_ap_service(db).aging_report(kind=kind, store_id=store_id, as_of=as_of)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
