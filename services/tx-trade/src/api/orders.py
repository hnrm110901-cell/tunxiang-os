"""交易域 API — 订单 CRUD + 支付 + 小票打印"""
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/trade", tags=["trade"])


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


# ─── 端点 ───

@router.post("/orders")
async def create_order(req: CreateOrderReq, request: Request):
    """开单"""
    # TODO: inject db session + OrderService
    return {"ok": True, "data": {"message": "Order creation endpoint ready"}, "error": None}


@router.post("/orders/{order_id}/items")
async def add_item(order_id: str, req: AddItemReq):
    """加菜"""
    return {"ok": True, "data": {"message": f"Add item to order {order_id}"}, "error": None}


@router.patch("/orders/{order_id}/items/{item_id}")
async def update_item(order_id: str, item_id: str, req: UpdateItemQtyReq):
    """改菜"""
    return {"ok": True, "data": {"message": f"Update item {item_id}"}, "error": None}


@router.delete("/orders/{order_id}/items/{item_id}")
async def remove_item(order_id: str, item_id: str):
    """删菜"""
    return {"ok": True, "data": {"message": f"Remove item {item_id}"}, "error": None}


@router.post("/orders/{order_id}/discount")
async def apply_discount(order_id: str, req: ApplyDiscountReq):
    """折扣"""
    return {"ok": True, "data": {"message": f"Apply discount to {order_id}"}, "error": None}


@router.post("/orders/{order_id}/settle")
async def settle_order(order_id: str):
    """结算"""
    return {"ok": True, "data": {"message": f"Settle order {order_id}"}, "error": None}


@router.post("/orders/{order_id}/cancel")
async def cancel_order(order_id: str, reason: str = ""):
    """取消"""
    return {"ok": True, "data": {"message": f"Cancel order {order_id}"}, "error": None}


@router.get("/orders/{order_id}")
async def get_order(order_id: str):
    """查询订单详情"""
    return {"ok": True, "data": {"message": f"Get order {order_id}"}, "error": None}


@router.post("/orders/{order_id}/payments")
async def create_payment(order_id: str, req: CreatePaymentReq):
    """支付"""
    return {"ok": True, "data": {"message": f"Payment for {order_id}"}, "error": None}


@router.post("/orders/{order_id}/refund")
async def refund(order_id: str, req: RefundReq):
    """退款"""
    return {"ok": True, "data": {"message": f"Refund for {order_id}"}, "error": None}


@router.get("/orders/{order_id}/payments")
async def get_payments(order_id: str):
    """查询支付记录"""
    return {"ok": True, "data": {"message": f"Payments for {order_id}"}, "error": None}


@router.post("/orders/{order_id}/print/receipt")
async def print_receipt(order_id: str):
    """打印客户小票"""
    return {"ok": True, "data": {"message": f"Print receipt for {order_id}"}, "error": None}


@router.post("/orders/{order_id}/print/kitchen")
async def print_kitchen(order_id: str, station: str = ""):
    """打印厨房单（按档口）"""
    return {"ok": True, "data": {"message": f"Print kitchen order for {order_id} station={station}"}, "error": None}
