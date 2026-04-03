"""交易域 API — 订单 CRUD + 支付 + 小票打印（已接通数据库）"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.order_service import OrderService
from ..services.payment_service import PaymentService
from ..services.receipt_service import ReceiptService

router = APIRouter(prefix="/api/v1/trade", tags=["trade"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


# ─── 请求模型 ───

class CreateOrderReq(BaseModel):
    store_id: str
    order_type: str = "dine_in"
    table_no: Optional[str] = None
    customer_id: Optional[str] = None
    waiter_id: Optional[str] = None


class AddItemReq(BaseModel):
    dish_id: str
    dish_name: str
    quantity: int
    unit_price_fen: int
    notes: Optional[str] = None
    customizations: Optional[dict] = None


class UpdateItemQtyReq(BaseModel):
    new_quantity: int


class ApplyDiscountReq(BaseModel):
    discount_fen: int
    reason: str = ""


class CreatePaymentReq(BaseModel):
    method: str
    amount_fen: int
    trade_no: Optional[str] = None
    credit_account_name: Optional[str] = None


class RefundReq(BaseModel):
    payment_id: str
    amount_fen: int
    refund_type: str = "full"
    reason: str = ""


# ─── 订单端点 ───

@router.post("/orders")
async def create_order(req: CreateOrderReq, request: Request, db: AsyncSession = Depends(get_db)):
    svc = OrderService(db, _get_tenant_id(request))
    result = await svc.create_order(
        store_id=req.store_id, order_type=req.order_type,
        table_no=req.table_no, customer_id=req.customer_id, waiter_id=req.waiter_id,
    )
    return {"ok": True, "data": result, "error": None}


@router.post("/orders/{order_id}/items")
async def add_item(order_id: str, req: AddItemReq, request: Request, db: AsyncSession = Depends(get_db)):
    svc = OrderService(db, _get_tenant_id(request))
    result = await svc.add_item(
        order_id=order_id, dish_id=req.dish_id, dish_name=req.dish_name,
        quantity=req.quantity, unit_price_fen=req.unit_price_fen,
        notes=req.notes, customizations=req.customizations,
    )
    return {"ok": True, "data": result, "error": None}


@router.patch("/orders/{order_id}/items/{item_id}")
async def update_item(order_id: str, item_id: str, req: UpdateItemQtyReq, request: Request, db: AsyncSession = Depends(get_db)):
    svc = OrderService(db, _get_tenant_id(request))
    result = await svc.update_item_quantity(item_id=item_id, new_quantity=req.new_quantity)
    return {"ok": True, "data": result, "error": None}


@router.delete("/orders/{order_id}/items/{item_id}")
async def remove_item(order_id: str, item_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    svc = OrderService(db, _get_tenant_id(request))
    result = await svc.remove_item(item_id=item_id)
    return {"ok": True, "data": result, "error": None}


@router.post("/orders/{order_id}/discount")
async def apply_discount(order_id: str, req: ApplyDiscountReq, request: Request, db: AsyncSession = Depends(get_db)):
    svc = OrderService(db, _get_tenant_id(request))
    result = await svc.apply_discount(order_id=order_id, discount_fen=req.discount_fen, reason=req.reason)
    return {"ok": True, "data": result, "error": None}


@router.post("/orders/{order_id}/settle")
async def settle_order(order_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    svc = OrderService(db, _get_tenant_id(request))
    result = await svc.settle_order(order_id=order_id)
    return {"ok": True, "data": result, "error": None}


@router.post("/orders/{order_id}/cancel")
async def cancel_order(order_id: str, reason: str = "", request: Request = None, db: AsyncSession = Depends(get_db)):
    svc = OrderService(db, _get_tenant_id(request))
    result = await svc.cancel_order(order_id=order_id, reason=reason)
    return {"ok": True, "data": result, "error": None}


@router.get("/orders/{order_id}")
async def get_order(order_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    svc = OrderService(db, _get_tenant_id(request))
    result = await svc.get_order(order_id=order_id)
    if not result:
        raise HTTPException(status_code=404, detail="Order not found")
    return {"ok": True, "data": result, "error": None}


# ─── 支付端点 ───

@router.post("/orders/{order_id}/payments")
async def create_payment(order_id: str, req: CreatePaymentReq, request: Request, db: AsyncSession = Depends(get_db)):
    svc = PaymentService(db, _get_tenant_id(request))
    result = await svc.create_payment(
        order_id=order_id, method=req.method, amount_fen=req.amount_fen,
        trade_no=req.trade_no, credit_account_name=req.credit_account_name,
    )
    return {"ok": True, "data": result, "error": None}


@router.post("/orders/{order_id}/refund")
async def refund(order_id: str, req: RefundReq, request: Request, db: AsyncSession = Depends(get_db)):
    svc = PaymentService(db, _get_tenant_id(request))
    result = await svc.process_refund(
        order_id=order_id, payment_id=req.payment_id,
        amount_fen=req.amount_fen, refund_type=req.refund_type, reason=req.reason,
    )
    return {"ok": True, "data": result, "error": None}


@router.get("/orders/{order_id}/payments")
async def get_payments(order_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    svc = PaymentService(db, _get_tenant_id(request))
    result = await svc.get_order_payments(order_id=order_id)
    return {"ok": True, "data": result, "error": None}


# ─── 打印端点 ───

@router.post("/orders/{order_id}/print/receipt")
async def print_receipt(order_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    svc = OrderService(db, _get_tenant_id(request))
    order = await svc.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    content = ReceiptService.format_receipt(order, store_name="屯象")
    return {"ok": True, "data": {"content_base64": content.hex(), "content_length": len(content)}, "error": None}


@router.post("/orders/{order_id}/print/kitchen")
async def print_kitchen(order_id: str, station: str = "", request: Request = None, db: AsyncSession = Depends(get_db)):
    svc = OrderService(db, _get_tenant_id(request))
    order = await svc.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if station:
        content = ReceiptService.format_kitchen_order(order, station=station)
        return {"ok": True, "data": {"station": station, "content_length": len(content)}, "error": None}

    # 自动按档口分单
    stations = ReceiptService.split_by_station(order)
    results = []
    for st, items in stations.items():
        station_order = {**order, "items": items}
        content = ReceiptService.format_kitchen_order(station_order, station=st)
        results.append({"station": st, "item_count": len(items), "content_length": len(content)})
    return {"ok": True, "data": {"stations": results}, "error": None}
