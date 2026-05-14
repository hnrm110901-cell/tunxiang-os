"""C5 收货验收 + 退货 + 调拨 API 路由 — 5 个端点

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""

from __future__ import annotations

from datetime import date
from typing import List

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db as _get_db
from shared.security.src.error_handler import safe_http_exception

try:
    # 作为包导入时（FastAPI 运行时），使用相对导入
    from ..services.cert_service import is_supplier_blocked_via_po
    from ..services.receiving_service import (
        confirm_transfer,
        create_receiving,
        create_transfer,
        get_central_warehouse_stock,
        reject_item,
    )
except ImportError:
    # sys.path 直接指向 src/ 时（测试环境），使用绝对导入
    from services.tx_supply.src.services.cert_service import (  # type: ignore[no-redef]
        is_supplier_blocked_via_po,
    )
    from services.tx_supply.src.services.receiving_service import (  # type: ignore[no-redef]
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
    db: AsyncSession = Depends(_get_db),
):
    """C5: 创建收货验收单。

    §19 P0-1 修复：v1 路径补 PRD-01 食安阻断。
    通过 purchase_order_id 反查 supplier_id 后调 is_supplier_blocked。
    PO 不存在 / supplier_id NULL → fail-closed 422（监管不接受匿名收货）。
    """
    # ── PRD-01 食安合规阻断（Tier 1 / fail-closed via PO lookup）─────────────
    if await is_supplier_blocked_via_po(
        db,
        tenant_id=x_tenant_id,
        purchase_order_id=body.purchase_order_id,
        today=date.today(),
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "SUPPLIER_CERT_EXPIRED",
                "message": "供应商证件已过期或采购单无效，无法收货",
            },
        )
    # ── 业务逻辑 ────────────────────────────────────────────────────────────
    try:
        result = await create_receiving(
            body.purchase_order_id,
            [i.model_dump() for i in body.items],
            body.receiver_id,
            x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise safe_http_exception(400, "请求参数无效", e) from e


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
        raise safe_http_exception(400, "请求参数无效", e) from e


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
        raise safe_http_exception(400, "请求参数无效", e) from e


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
        raise safe_http_exception(400, "请求参数无效", e) from e


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
