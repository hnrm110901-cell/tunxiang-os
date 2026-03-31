"""门店调拨 API 路由

端点：
  POST /api/v1/transfers                                — 创建调拨申请
  GET  /api/v1/transfers                                — 调拨单列表
  GET  /api/v1/transfers/{order_id}                     — 调拨单详情
  POST /api/v1/transfers/{order_id}/approve             — 审批通过
  POST /api/v1/transfers/{order_id}/ship                — 发货（from_store 扣库存）
  POST /api/v1/transfers/{order_id}/receive             — 收货（to_store 加库存）
  POST /api/v1/transfers/{order_id}/cancel              — 取消调拨
  GET  /api/v1/transfers/inventory-check                — 查询门店库存（调拨决策）

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from shared.ontology.src.database import get_db as _get_db

from ..services.transfer_service import (
    InsufficientStockError,
    approve_transfer_order,
    cancel_transfer_order,
    create_transfer_order,
    get_brand_ingredient_overview,
    get_brand_low_stock_alert,
    get_store_ingredient_stock,
    get_transfer_order,
    list_transfer_orders,
    receive_transfer_order,
    ship_transfer_order,
)

router = APIRouter(prefix="/api/v1/transfers", tags=["transfer"])


# ─── 请求模型 ─────────────────────────────────────────────


class TransferItemIn(BaseModel):
    ingredient_id: str
    ingredient_name: str
    requested_quantity: Decimal = Field(gt=Decimal("0"))
    unit: str


class CreateTransferRequest(BaseModel):
    from_store_id: str
    to_store_id: str
    items: List[TransferItemIn]
    transfer_reason: Optional[str] = None
    requested_by: Optional[str] = None
    notes: Optional[str] = None


class ApproveItemIn(BaseModel):
    item_id: str
    approved_quantity: Decimal = Field(ge=Decimal("0"))


class ApproveTransferRequest(BaseModel):
    approved_by: str
    approved_items: List[ApproveItemIn] = Field(default_factory=list)


class ShipItemIn(BaseModel):
    item_id: str
    shipped_quantity: Decimal = Field(ge=Decimal("0"))
    batch_no: Optional[str] = None


class ShipTransferRequest(BaseModel):
    shipped_items: List[ShipItemIn]
    operator_id: Optional[str] = None


class ReceiveItemIn(BaseModel):
    item_id: str
    received_quantity: Decimal = Field(ge=Decimal("0"))


class ReceiveTransferRequest(BaseModel):
    received_items: List[ReceiveItemIn]
    operator_id: Optional[str] = None


class CancelTransferRequest(BaseModel):
    cancelled_by: Optional[str] = None
    reason: Optional[str] = None


# ─── 路由 ─────────────────────────────────────────────────


@router.post("")
async def create_transfer(
    body: CreateTransferRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """创建调拨申请（status='draft'）"""
    try:
        result = await create_transfer_order(
            tenant_id=x_tenant_id,
            from_store_id=body.from_store_id,
            to_store_id=body.to_store_id,
            items=[i.model_dump() for i in body.items],
            db=db,
            transfer_reason=body.transfer_reason,
            requested_by=body.requested_by,
            notes=body.notes,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("")
async def list_transfers(
    store_id: Optional[str] = Query(None),
    role: Optional[str] = Query(None, description="from | to | null（两者均包含）"),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """调拨单列表"""
    result = await list_transfer_orders(
        tenant_id=x_tenant_id,
        db=db,
        store_id=store_id,
        role=role,
        status=status,
        page=page,
        size=size,
    )
    return {"ok": True, "data": result}


@router.get("/inventory-check")
async def inventory_check(
    store_id: str = Query(...),
    ingredient_id: str = Query(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """查询门店某食材库存（调拨决策参考）。

    NOTE: 此路由必须放在 /{order_id} 之前，避免路径冲突。
    """
    try:
        result = await get_store_ingredient_stock(
            store_id=store_id,
            ingredient_id=ingredient_id,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{order_id}")
async def get_transfer(
    order_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """调拨单详情（含明细）"""
    try:
        result = await get_transfer_order(
            order_id=order_id,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{order_id}/approve")
async def approve_transfer(
    order_id: str,
    body: ApproveTransferRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """审批调拨单。

    检查 from_store 库存是否充足。approved_items 为空时，全部按申请数量审批。
    """
    try:
        result = await approve_transfer_order(
            order_id=order_id,
            tenant_id=x_tenant_id,
            db=db,
            approved_by=body.approved_by,
            approved_items=[i.model_dump() for i in body.approved_items],
        )
        return {"ok": True, "data": result}
    except InsufficientStockError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{order_id}/ship")
async def ship_transfer(
    order_id: str,
    body: ShipTransferRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """发货。

    从 from_store 扣减库存，记录 transfer_out 流水。
    """
    try:
        result = await ship_transfer_order(
            order_id=order_id,
            tenant_id=x_tenant_id,
            db=db,
            shipped_items=[i.model_dump() for i in body.shipped_items],
            operator_id=body.operator_id,
        )
        return {"ok": True, "data": result}
    except InsufficientStockError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{order_id}/receive")
async def receive_transfer(
    order_id: str,
    body: ReceiveTransferRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """确认收货。

    向 to_store 增加库存，记录 transfer_in 流水。
    若 received < shipped，差额记录为运输损耗。
    """
    try:
        result = await receive_transfer_order(
            order_id=order_id,
            tenant_id=x_tenant_id,
            db=db,
            received_items=[i.model_dump() for i in body.received_items],
            operator_id=body.operator_id,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{order_id}/cancel")
async def cancel_transfer(
    order_id: str,
    body: CancelTransferRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """取消调拨单（仅 draft/approved 状态可取消）。"""
    try:
        result = await cancel_transfer_order(
            order_id=order_id,
            tenant_id=x_tenant_id,
            db=db,
            cancelled_by=body.cancelled_by,
            reason=body.reason,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
