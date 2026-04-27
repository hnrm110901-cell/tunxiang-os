"""收货验收流程 API V2 — 完整验收流程

端点：
  POST /api/v1/receiving/orders                         — 创建收货单
  GET  /api/v1/receiving/orders                         — 收货单列表
  GET  /api/v1/receiving/orders/{order_id}              — 收货单详情
  POST /api/v1/receiving/orders/{order_id}/items/{item_id}/inspect  — 单项验收
  POST /api/v1/receiving/orders/{order_id}/complete     — 完成验收（入库）
  POST /api/v1/receiving/orders/{order_id}/reject-all   — 全部拒收

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db as _get_db

from ..services.receiving_v2_service import (
    complete_receiving,
    create_receiving_order,
    get_receiving_order,
    inspect_item,
    list_receiving_orders,
    reject_all,
)

router = APIRouter(prefix="/api/v1/receiving", tags=["receiving-v2"])


# ─── 请求模型 ─────────────────────────────────────────────


class ReceivingOrderItemIn(BaseModel):
    ingredient_id: str
    ingredient_name: str
    expected_quantity: Decimal = Field(gt=Decimal("0"))
    expected_unit: str
    unit_price_fen: Optional[int] = None


class CreateReceivingOrderRequest(BaseModel):
    store_id: str
    supplier_id: Optional[str] = None
    delivery_note_no: Optional[str] = None
    procurement_order_id: Optional[str] = None
    receiver_id: Optional[str] = None
    items: List[ReceivingOrderItemIn]


class InspectItemRequest(BaseModel):
    actual_quantity: Decimal = Field(ge=Decimal("0"))
    accepted_quantity: Decimal = Field(ge=Decimal("0"))
    unit_price_fen: Optional[int] = None
    batch_no: Optional[str] = None
    production_date: Optional[date] = None
    expiry_date: Optional[date] = None
    rejection_reason: Optional[str] = None


class CompleteReceivingRequest(BaseModel):
    store_id: str
    signer_id: Optional[str] = None


class RejectAllRequest(BaseModel):
    rejection_reason: Optional[str] = None


# ─── 路由 ─────────────────────────────────────────────────


@router.post("/orders")
async def create_order(
    body: CreateReceivingOrderRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """创建收货单。

    若传入 procurement_order_id，系统会从采购单预填预期数量。
    """
    try:
        result = await create_receiving_order(
            tenant_id=x_tenant_id,
            store_id=body.store_id,
            supplier_id=body.supplier_id,
            delivery_note_no=body.delivery_note_no,
            receiver_id=body.receiver_id,
            items=[i.model_dump() for i in body.items],
            db=db,
            procurement_order_id=body.procurement_order_id,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/orders")
async def list_orders(
    store_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """收货单列表（支持按门店、状态、日期过滤）"""
    result = await list_receiving_orders(
        tenant_id=x_tenant_id,
        db=db,
        store_id=store_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
        page=page,
        size=size,
    )
    return {"ok": True, "data": result}


@router.get("/orders/{order_id}")
async def get_order(
    order_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """收货单详情（含明细）"""
    try:
        result = await get_receiving_order(
            order_id=order_id,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/orders/{order_id}/items/{item_id}/inspect")
async def inspect_receiving_item(
    order_id: str,
    item_id: str,
    body: InspectItemRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """对单项食材进行验收。

    accepted_quantity <= actual_quantity，差值自动记为拒收。
    """
    try:
        result = await inspect_item(
            order_id=order_id,
            item_id=item_id,
            tenant_id=x_tenant_id,
            db=db,
            actual_quantity=body.actual_quantity,
            accepted_quantity=body.accepted_quantity,
            unit_price_fen=body.unit_price_fen,
            batch_no=body.batch_no,
            production_date=body.production_date,
            expiry_date=body.expiry_date,
            rejection_reason=body.rejection_reason,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/orders/{order_id}/complete")
async def complete_order(
    order_id: str,
    body: CompleteReceivingRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """完成验收。

    - 将所有验收通过数量入库（更新 ingredients.current_quantity + 写 ingredient_transactions）
    - 状态变为 fully_received / partially_received / rejected
    """
    try:
        result = await complete_receiving(
            order_id=order_id,
            tenant_id=x_tenant_id,
            store_id=body.store_id,
            db=db,
            signer_id=body.signer_id,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/orders/{order_id}/reject-all")
async def reject_order_all(
    order_id: str,
    body: RejectAllRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """整批拒收（整批退货，不入库）"""
    try:
        result = await reject_all(
            order_id=order_id,
            tenant_id=x_tenant_id,
            db=db,
            rejection_reason=body.rejection_reason,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
