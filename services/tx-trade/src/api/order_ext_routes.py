"""点单扩展 API — 赠菜/拆单/并单/异常改单"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services import order_extensions as ext

router = APIRouter(prefix="/api/v1/trade/orders", tags=["order-extensions"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


# ─── 请求模型 ───


class GiftDishReq(BaseModel):
    dish_id: str
    quantity: int
    reason: str
    approver_id: str


class SplitOrderReq(BaseModel):
    items_groups: list[list[str]]


class MergeOrdersReq(BaseModel):
    order_ids: list[str]


class OrderChangeReq(BaseModel):
    changes: dict
    reason: str


class ApproveChangeReq(BaseModel):
    approver_id: str


# ─── 端点 ───


@router.post("/{order_id}/gift-dish")
async def gift_dish(
    order_id: str,
    body: GiftDishReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """赠菜（需审批人）"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await ext.gift_dish(
            order_id=order_id,
            dish_id=body.dish_id,
            quantity=body.quantity,
            reason=body.reason,
            approver_id=body.approver_id,
            tenant_id=tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{order_id}/split")
async def split_order(
    order_id: str,
    body: SplitOrderReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """拆单"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await ext.split_order(
            order_id=order_id,
            items_groups=body.items_groups,
            tenant_id=tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/merge")
async def merge_orders(
    body: MergeOrdersReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """并单"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await ext.merge_orders(
            order_ids=body.order_ids,
            tenant_id=tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{order_id}/change-request")
async def request_order_change(
    order_id: str,
    body: OrderChangeReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """异常改单申请"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await ext.request_order_change(
            order_id=order_id,
            changes=body.changes,
            reason=body.reason,
            tenant_id=tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/changes/{change_id}/approve")
async def approve_order_change(
    change_id: str,
    body: ApproveChangeReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """改单审批"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await ext.approve_order_change(
            change_id=change_id,
            approver_id=body.approver_id,
            tenant_id=tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
