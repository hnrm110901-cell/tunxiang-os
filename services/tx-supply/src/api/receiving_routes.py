"""C5 收货验收 + 退货 + 调拨 API 路由 — 5 个端点

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

try:
    # 作为包导入时（FastAPI 运行时），使用相对导入
    from ..services.receiving_service import (
        confirm_transfer,
        create_receiving,
        create_transfer,
        get_central_warehouse_stock,
        reject_item,
    )
except ImportError:
    # sys.path 直接指向 src/ 时（测试环境），使用绝对导入
    from services.receiving_service import (  # type: ignore[no-redef]
        confirm_transfer,
        create_receiving,
        create_transfer,
        get_central_warehouse_stock,
        reject_item,
    )

router = APIRouter(prefix="/api/v1/supply", tags=["receiving"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class ReceivingItemRequest(BaseModel):
    ingredient_id: str
    name: str = ""
    ordered_qty: float = 0
    received_qty: float = Field(ge=0)
    quality: str = Field("pass", pattern="^(pass|fail|partial)$")
    notes: str = ""


class CreateReceivingRequest(BaseModel):
    purchase_order_id: str
    items: List[ReceivingItemRequest]
    receiver_id: str


class RejectItemRequest(BaseModel):
    item_id: str
    reason: str
    quantity: float = Field(gt=0)


class TransferItemRequest(BaseModel):
    ingredient_id: str
    name: str = ""
    quantity: float = Field(gt=0)
    unit: str = ""


class CreateTransferRequest(BaseModel):
    from_store_id: str
    to_store_id: str
    items: List[TransferItemRequest]


class ConfirmTransferRequest(BaseModel):
    confirmed_by: str
    role: str = Field(..., pattern="^(sender|receiver)$")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 收货验收
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/receiving")
async def create_receiving(
    body: CreateReceivingRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """C5: 创建收货验收单"""
    try:
        result = await create_receiving(
            body.purchase_order_id,
            [i.model_dump() for i in body.items],
            body.receiver_id,
            x_tenant_id,
            db=None,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 退货
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/receiving/{receiving_id}/reject")
async def reject_item(
    receiving_id: str,
    body: RejectItemRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """C5: 退货"""
    try:
        result = await reject_item(
            receiving_id,
            body.item_id,
            body.reason,
            body.quantity,
            x_tenant_id,
            db=None,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 门店调拨
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/transfers")
async def create_transfer(
    body: CreateTransferRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """C5: 发起门店调拨"""
    try:
        result = await create_transfer(
            body.from_store_id,
            body.to_store_id,
            [i.model_dump() for i in body.items],
            x_tenant_id,
            db=None,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 调拨确认
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/transfers/{transfer_id}/confirm")
async def confirm_transfer(
    transfer_id: str,
    body: ConfirmTransferRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """C5: 确认调拨（发方/收方）"""
    try:
        result = await confirm_transfer(
            transfer_id,
            body.confirmed_by,
            x_tenant_id,
            db=None,
            role=body.role,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 中央仓库存
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/warehouse/stock")
async def get_central_warehouse_stock(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """C5: 中央仓库存查询"""
    result = await get_central_warehouse_stock(x_tenant_id, db=None)
    return {"ok": True, "data": result}
