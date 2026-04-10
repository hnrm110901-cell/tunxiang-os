"""
宴席支付闭环路由 — 定金/尾款状态机

路由前缀：/api/v1/trade/banquet

端点：
  # 宴席订单管理
  GET    /orders                            — 订单列表（date/payment_status/store_id过滤）
  GET    /orders/{order_id}                 — 订单详情（含支付记录）
  POST   /orders                            — 创建宴席预订
  PUT    /orders/{order_id}                 — 更新预订信息
  POST   /orders/{order_id}/cancel         — 取消预订

  # 支付状态机
  POST   /orders/{order_id}/pay-deposit    — 支付定金
  POST   /orders/{order_id}/pay-balance    — 支付尾款
  POST   /orders/{order_id}/refund         — 退款
  GET    /orders/{order_id}/receipt        — 支付凭证

  # 报表
  GET    /stats                             — 月度预订统计
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/trade/banquet", tags=["banquet-order-payment"])


# ─── 工具函数 ────────────────────────────────────────────────────────────────

def _ok(data: object) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: str = "BAD_REQUEST") -> dict:
    return {"ok": False, "data": None, "error": {"code": code, "message": msg}}


def _get_tenant_id(request: Request) -> str:
    tid = (
        getattr(request.state, "tenant_id", None)
        or request.headers.get("X-Tenant-ID", "")
    )
    if not tid:
        raise HTTPException(status_code=400, detail="Missing X-Tenant-ID")
    return tid


def _fen_to_yuan_str(fen: int) -> str:
    """将分转为"¥元"字符串，用于凭证展示。"""
    yuan = Decimal(fen) / Decimal(100)
    return f"¥{yuan:.2f}"


# ─── Mock 数据存储 ──────────────────────────────────────────────────────────

MOCK_BANQUET_ORDERS: dict[str, dict] = {
    "ban-001": {
        "id": "ban-001",
        "tenant_id": "t-demo-001",
        "store_id": "s-demo-001",
        "contact_name": "张总",
        "contact_phone": "13800138001",
        "banquet_date": "2026-05-01",
        "banquet_time": "18:00",
        "guest_count": 20,
        "table_ids": [],
        "total_fen": 580000,
        "deposit_rate": "0.30",
        "deposit_fen": 174000,
        "balance_fen": 406000,
        "deposit_status": "paid",
        "balance_status": "unpaid",
        "payment_status": "deposit_paid",
        "status": "confirmed",
        "notes": "需要婚庆布置",
        "cancel_reason": None,
        "cancelled_at": None,
        "is_deleted": False,
        "created_at": "2026-04-01T10:00:00+08:00",
        "updated_at": "2026-04-01T12:00:00+08:00",
    },
    "ban-002": {
        "id": "ban-002",
        "tenant_id": "t-demo-001",
        "store_id": "s-demo-001",
        "contact_name": "李总婚宴",
        "contact_phone": "13800138002",
        "banquet_date": "2026-04-20",
        "banquet_time": "12:00",
        "guest_count": 60,
        "table_ids": [],
        "total_fen": 1280000,
        "deposit_rate": "0.30",
        "deposit_fen": 384000,
        "balance_fen": 896000,
        "deposit_status": "paid",
        "balance_status": "paid",
        "payment_status": "fully_paid",
        "status": "confirmed",
        "notes": "60人婚宴，徐记海鲜全席",
        "cancel_reason": None,
        "cancelled_at": None,
        "is_deleted": False,
        "created_at": "2026-03-15T09:00:00+08:00",
        "updated_at": "2026-04-05T14:00:00+08:00",
    },
    "ban-003": {
        "id": "ban-003",
        "tenant_id": "t-demo-001",
        "store_id": "s-demo-001",
        "contact_name": "王氏家宴",
        "contact_phone": "13800138003",
        "banquet_date": "2026-04-25",
        "banquet_time": "19:00",
        "guest_count": 12,
        "table_ids": [],
        "total_fen": 320000,
        "deposit_rate": "0.30",
        "deposit_fen": 96000,
        "balance_fen": 224000,
        "deposit_status": "unpaid",
        "balance_status": "unpaid",
        "payment_status": "unpaid",
        "status": "pending",
        "notes": "",
        "cancel_reason": None,
        "cancelled_at": None,
        "is_deleted": False,
        "created_at": "2026-04-06T08:00:00+08:00",
        "updated_at": "2026-04-06T08:00:00+08:00",
    },
}

# 支付记录：banquet_order_id -> list[payment_record]
MOCK_PAYMENTS: dict[str, list[dict]] = {
    "ban-001": [
        {
            "id": "pay-001-dep",
            "tenant_id": "t-demo-001",
            "banquet_order_id": "ban-001",
            "payment_stage": "deposit",
            "amount_fen": 174000,
            "payment_method": "wechat",
            "payment_status": "paid",
            "transaction_id": "WX20260401120001",
            "paid_at": "2026-04-01T12:00:00+08:00",
            "refund_amount_fen": 0,
            "refunded_at": None,
            "operator_id": None,
            "notes": "微信支付定金",
            "created_at": "2026-04-01T12:00:00+08:00",
            "updated_at": "2026-04-01T12:00:00+08:00",
        }
    ],
    "ban-002": [
        {
            "id": "pay-002-dep",
            "tenant_id": "t-demo-001",
            "banquet_order_id": "ban-002",
            "payment_stage": "deposit",
            "amount_fen": 384000,
            "payment_method": "wechat",
            "payment_status": "paid",
            "transaction_id": "WX20260315090001",
            "paid_at": "2026-03-15T09:30:00+08:00",
            "refund_amount_fen": 0,
            "refunded_at": None,
            "operator_id": None,
            "notes": "",
            "created_at": "2026-03-15T09:30:00+08:00",
            "updated_at": "2026-03-15T09:30:00+08:00",
        },
        {
            "id": "pay-002-bal",
            "tenant_id": "t-demo-001",
            "banquet_order_id": "ban-002",
            "payment_stage": "balance",
            "amount_fen": 896000,
            "payment_method": "transfer",
            "payment_status": "paid",
            "transaction_id": "TF20260405140001",
            "paid_at": "2026-04-05T14:00:00+08:00",
            "refund_amount_fen": 0,
            "refunded_at": None,
            "operator_id": None,
            "notes": "对公转账",
            "created_at": "2026-04-05T14:00:00+08:00",
            "updated_at": "2026-04-05T14:00:00+08:00",
        },
    ],
    "ban-003": [],
}


# ─── Request/Response Models ──────────────────────────────────────────────

class CreateOrderReq(BaseModel):
    store_id: str = Field(..., min_length=1)
    contact_name: str = Field(..., min_length=1, max_length=50)
    contact_phone: str = Field(..., min_length=1, max_length=20)
    banquet_date: str = Field(..., description="YYYY-MM-DD")
    banquet_time: str = Field(..., description="HH:MM")
    guest_count: int = Field(..., ge=1)
    table_ids: list[str] = []
    total_fen: int = Field(..., gt=0)
    deposit_rate: float = Field(0.30, gt=0, le=1.0, description="定金比例，默认0.30")
    notes: str = ""


class UpdateOrderReq(BaseModel):
    contact_name: Optional[str] = Field(None, min_length=1, max_length=50)
    contact_phone: Optional[str] = Field(None, min_length=1, max_length=20)
    banquet_date: Optional[str] = None
    banquet_time: Optional[str] = None
    guest_count: Optional[int] = Field(None, ge=1)
    table_ids: Optional[list[str]] = None
    total_fen: Optional[int] = Field(None, gt=0)
    deposit_rate: Optional[float] = Field(None, gt=0, le=1.0)
    notes: Optional[str] = None


class CancelOrderReq(BaseModel):
    cancel_reason: str = Field(..., min_length=1)


class PayDepositReq(BaseModel):
    payment_method: str = Field(
        ...,
        pattern="^(wechat|alipay|cash|card|transfer)$",
        description="wechat/alipay/cash/card/transfer",
    )
    amount_fen: int = Field(..., gt=0, description="实付定金金额（分），不得少于应付定金")
    transaction_id: Optional[str] = Field(None, max_length=100, description="第三方支付流水号")
    notes: str = ""


class PayBalanceReq(BaseModel):
    payment_method: str = Field(
        ...,
        pattern="^(wechat|alipay|cash|card|transfer)$",
    )
    amount_fen: int = Field(..., gt=0, description="实付尾款金额（分），不得少于应付尾款")
    transaction_id: Optional[str] = Field(None, max_length=100)
    notes: str = ""


class RefundReq(BaseModel):
    refund_type: str = Field(
        ...,
        pattern="^(deposit|balance|full)$",
        description="deposit=退定金, balance=退尾款, full=全额退款",
    )
    reason: str = Field(..., min_length=1)
    amount_fen: int = Field(..., gt=0)


# ─── 1. 宴席订单列表 ──────────────────────────────────────────────────────────

@router.get("/orders")
async def list_orders(
    request: Request,
    banquet_date: Optional[str] = None,
    payment_status: Optional[str] = None,
    store_id: Optional[str] = None,
    page: int = 1,
    size: int = 20,
):
    """宴席订单列表，支持日期/支付状态/门店过滤。"""
    tenant_id = _get_tenant_id(request)

    items = [
        o for o in MOCK_BANQUET_ORDERS.values()
        if not o["is_deleted"] and o["tenant_id"] == tenant_id
    ]

    if banquet_date:
        items = [o for o in items if o["banquet_date"] == banquet_date]
    if payment_status:
        items = [o for o in items if o["payment_status"] == payment_status]
    if store_id:
        items = [o for o in items if o["store_id"] == store_id]

    total = len(items)
    start = (page - 1) * size
    paginated = items[start: start + size]

    return _ok({"items": paginated, "total": total, "page": page, "size": size})


# ─── 2. 宴席订单详情 ──────────────────────────────────────────────────────────

@router.get("/orders/{order_id}")
async def get_order(order_id: str, request: Request):
    """宴席订单详情，含支付记录列表。"""
    tenant_id = _get_tenant_id(request)
    order = MOCK_BANQUET_ORDERS.get(order_id)
    if not order or order["is_deleted"] or order["tenant_id"] != tenant_id:
        return _err("订单不存在", "NOT_FOUND")

    payments = MOCK_PAYMENTS.get(order_id, [])
    return _ok({**order, "payments": payments})


# ─── 3. 创建宴席预订 ──────────────────────────────────────────────────────────

@router.post("/orders")
async def create_order(body: CreateOrderReq, request: Request):
    """
    创建宴席预订。
    deposit_fen = total_fen × deposit_rate（四舍五入到分），
    balance_fen = total_fen − deposit_fen。
    """
    tenant_id = _get_tenant_id(request)

    deposit_fen = round(body.total_fen * body.deposit_rate)
    balance_fen = body.total_fen - deposit_fen
    now_str = datetime.now().astimezone().isoformat()
    order_id = str(uuid.uuid4())

    order: dict = {
        "id": order_id,
        "tenant_id": tenant_id,
        "store_id": body.store_id,
        "contact_name": body.contact_name,
        "contact_phone": body.contact_phone,
        "banquet_date": body.banquet_date,
        "banquet_time": body.banquet_time,
        "guest_count": body.guest_count,
        "table_ids": body.table_ids,
        "total_fen": body.total_fen,
        "deposit_rate": str(body.deposit_rate),
        "deposit_fen": deposit_fen,
        "balance_fen": balance_fen,
        "deposit_status": "unpaid",
        "balance_status": "unpaid",
        "payment_status": "unpaid",
        "status": "pending",
        "notes": body.notes,
        "cancel_reason": None,
        "cancelled_at": None,
        "is_deleted": False,
        "created_at": now_str,
        "updated_at": now_str,
    }

    MOCK_BANQUET_ORDERS[order_id] = order
    MOCK_PAYMENTS[order_id] = []

    logger.info("banquet_order.created", order_id=order_id, tenant_id=tenant_id,
                total_fen=body.total_fen, deposit_fen=deposit_fen)
    return _ok(order)


# ─── 4. 更新预订信息 ──────────────────────────────────────────────────────────

@router.put("/orders/{order_id}")
async def update_order(order_id: str, body: UpdateOrderReq, request: Request):
    """
    更新预订信息。仅允许在未支付（payment_status=unpaid）或只付了定金时修改。
    若已全额支付则不可修改。
    """
    tenant_id = _get_tenant_id(request)
    order = MOCK_BANQUET_ORDERS.get(order_id)
    if not order or order["is_deleted"] or order["tenant_id"] != tenant_id:
        return _err("订单不存在", "NOT_FOUND")

    if order["payment_status"] == "fully_paid":
        raise HTTPException(
            status_code=400,
            detail="已全额支付的订单不可修改，如需调整请联系管理员",
        )
    if order["payment_status"] == "refunded":
        raise HTTPException(status_code=400, detail="已退款的订单不可修改")

    updates = body.model_dump(exclude_none=True)

    # 若更新了总额或定金比例，重新计算 deposit_fen / balance_fen
    new_total = updates.get("total_fen", order["total_fen"])
    new_rate = float(updates.get("deposit_rate", order["deposit_rate"]))
    if "total_fen" in updates or "deposit_rate" in updates:
        new_deposit = round(new_total * new_rate)
        updates["deposit_fen"] = new_deposit
        updates["balance_fen"] = new_total - new_deposit
        updates["deposit_rate"] = str(new_rate)

    updates["updated_at"] = datetime.now().astimezone().isoformat()
    order.update(updates)

    logger.info("banquet_order.updated", order_id=order_id, tenant_id=tenant_id)
    return _ok(order)


# ─── 5. 取消预订 ─────────────────────────────────────────────────────────────

@router.post("/orders/{order_id}/cancel")
async def cancel_order(order_id: str, body: CancelOrderReq, request: Request):
    """
    取消预订。
    - 未支付：直接取消。
    - 已付定金（balance_status=unpaid）：需先退定金，本接口仅标记取消，
      退款通过 /refund 端点处理。
    - 已全额支付：不允许直接取消，须走退款流程再取消。
    """
    tenant_id = _get_tenant_id(request)
    order = MOCK_BANQUET_ORDERS.get(order_id)
    if not order or order["is_deleted"] or order["tenant_id"] != tenant_id:
        return _err("订单不存在", "NOT_FOUND")

    if order["status"] == "cancelled":
        return _err("订单已取消", "ALREADY_CANCELLED")

    if order["payment_status"] == "fully_paid":
        raise HTTPException(
            status_code=400,
            detail="已全额支付的订单请先完成退款，再取消预订",
        )

    now_str = datetime.now().astimezone().isoformat()
    order["status"] = "cancelled"
    order["cancel_reason"] = body.cancel_reason
    order["cancelled_at"] = now_str
    order["updated_at"] = now_str

    logger.info("banquet_order.cancelled", order_id=order_id,
                reason=body.cancel_reason, tenant_id=tenant_id)
    return _ok(order)


# ─── 6. 支付定金 ─────────────────────────────────────────────────────────────

@router.post("/orders/{order_id}/pay-deposit")
async def pay_deposit(order_id: str, body: PayDepositReq, request: Request):
    """
    支付定金。

    状态机规则：
    - deposit_status 必须是 unpaid（不重复收定金）
    - amount_fen 必须 >= deposit_fen（不允许欠付定金）
    - 若 amount_fen >= total_fen，视为全额支付，同时更新 balance_status=paid
    - 返回：更新后的订单状态 + 支付凭证
    """
    tenant_id = _get_tenant_id(request)
    order = MOCK_BANQUET_ORDERS.get(order_id)
    if not order or order["is_deleted"] or order["tenant_id"] != tenant_id:
        return _err("订单不存在", "NOT_FOUND")

    if order["status"] == "cancelled":
        raise HTTPException(status_code=400, detail="订单已取消，不可支付")

    if order["deposit_status"] == "paid":
        raise HTTPException(status_code=400, detail="定金已支付，请勿重复操作")

    deposit_fen: int = order["deposit_fen"]
    if body.amount_fen < deposit_fen:
        raise HTTPException(
            status_code=400,
            detail=(
                f"支付金额不足：应付定金 {_fen_to_yuan_str(deposit_fen)}，"
                f"实付 {_fen_to_yuan_str(body.amount_fen)}"
            ),
        )

    now_str = datetime.now().astimezone().isoformat()
    pay_id = str(uuid.uuid4())

    payment_rec = {
        "id": pay_id,
        "tenant_id": tenant_id,
        "banquet_order_id": order_id,
        "payment_stage": "deposit",
        "amount_fen": body.amount_fen,
        "payment_method": body.payment_method,
        "payment_status": "paid",
        "transaction_id": body.transaction_id,
        "paid_at": now_str,
        "refund_amount_fen": 0,
        "refunded_at": None,
        "operator_id": None,
        "notes": body.notes,
        "created_at": now_str,
        "updated_at": now_str,
    }
    MOCK_PAYMENTS.setdefault(order_id, []).append(payment_rec)

    # 更新订单状态
    order["deposit_status"] = "paid"
    order["updated_at"] = now_str

    total_fen: int = order["total_fen"]
    if body.amount_fen >= total_fen:
        # 全额支付
        order["balance_status"] = "paid"
        order["payment_status"] = "fully_paid"
    else:
        order["payment_status"] = "deposit_paid"

    logger.info(
        "banquet_payment.deposit_paid",
        order_id=order_id,
        amount_fen=body.amount_fen,
        payment_status=order["payment_status"],
        tenant_id=tenant_id,
    )
    return _ok({
        "order": order,
        "payment": payment_rec,
        "receipt_summary": _build_receipt_summary(order, payment_rec),
    })


# ─── 7. 支付尾款 ─────────────────────────────────────────────────────────────

@router.post("/orders/{order_id}/pay-balance")
async def pay_balance(order_id: str, body: PayBalanceReq, request: Request):
    """
    支付尾款。

    状态机规则：
    - 前置检查：deposit_status 必须是 paid（定金未付不得支付尾款）
    - balance_status 必须是 unpaid（不重复收尾款）
    - amount_fen 必须 >= balance_fen
    - 成功后：payment_status=fully_paid, balance_status=paid
    """
    tenant_id = _get_tenant_id(request)
    order = MOCK_BANQUET_ORDERS.get(order_id)
    if not order or order["is_deleted"] or order["tenant_id"] != tenant_id:
        return _err("订单不存在", "NOT_FOUND")

    if order["status"] == "cancelled":
        raise HTTPException(status_code=400, detail="订单已取消，不可支付")

    if order["deposit_status"] != "paid":
        raise HTTPException(
            status_code=400,
            detail="请先支付定金，再支付尾款",
        )

    if order["balance_status"] == "paid":
        raise HTTPException(status_code=400, detail="尾款已支付，请勿重复操作")

    balance_fen: int = order["balance_fen"]
    if body.amount_fen < balance_fen:
        raise HTTPException(
            status_code=400,
            detail=(
                f"支付金额不足：应付尾款 {_fen_to_yuan_str(balance_fen)}，"
                f"实付 {_fen_to_yuan_str(body.amount_fen)}"
            ),
        )

    now_str = datetime.now().astimezone().isoformat()
    pay_id = str(uuid.uuid4())

    payment_rec = {
        "id": pay_id,
        "tenant_id": tenant_id,
        "banquet_order_id": order_id,
        "payment_stage": "balance",
        "amount_fen": body.amount_fen,
        "payment_method": body.payment_method,
        "payment_status": "paid",
        "transaction_id": body.transaction_id,
        "paid_at": now_str,
        "refund_amount_fen": 0,
        "refunded_at": None,
        "operator_id": None,
        "notes": body.notes,
        "created_at": now_str,
        "updated_at": now_str,
    }
    MOCK_PAYMENTS.setdefault(order_id, []).append(payment_rec)

    order["balance_status"] = "paid"
    order["payment_status"] = "fully_paid"
    order["updated_at"] = now_str

    all_payments = MOCK_PAYMENTS.get(order_id, [])

    logger.info(
        "banquet_payment.balance_paid",
        order_id=order_id,
        amount_fen=body.amount_fen,
        tenant_id=tenant_id,
    )
    return _ok({
        "order": order,
        "payment": payment_rec,
        "all_payments": all_payments,
    })


# ─── 8. 退款 ─────────────────────────────────────────────────────────────────

@router.post("/orders/{order_id}/refund")
async def refund_payment(order_id: str, body: RefundReq, request: Request):
    """
    退款。

    状态机规则：
    - deposit 退定金：
        * deposit_status=paid 且 balance_status=unpaid（宴席尚未结束，定金可退）
        * 不允许在已全额支付后仅退定金（应走 full 退款）
    - balance 退尾款：
        * payment_status=fully_paid
    - full 全额退款：
        * payment_status 为 deposit_paid 或 fully_paid
    """
    tenant_id = _get_tenant_id(request)
    order = MOCK_BANQUET_ORDERS.get(order_id)
    if not order or order["is_deleted"] or order["tenant_id"] != tenant_id:
        return _err("订单不存在", "NOT_FOUND")

    now_str = datetime.now().astimezone().isoformat()
    payments = MOCK_PAYMENTS.get(order_id, [])

    if body.refund_type == "deposit":
        if order["deposit_status"] != "paid":
            raise HTTPException(status_code=400, detail="定金尚未支付，无法退款")
        if order["balance_status"] == "paid":
            raise HTTPException(
                status_code=400,
                detail="已全额支付，不可仅退定金，请使用 refund_type=full 申请全额退款",
            )
        # 找到定金支付记录
        deposit_pays = [p for p in payments
                        if p["payment_stage"] == "deposit" and p["payment_status"] == "paid"]
        if not deposit_pays:
            raise HTTPException(status_code=400, detail="未找到有效定金支付记录")
        target_pay = deposit_pays[-1]
        if body.amount_fen > target_pay["amount_fen"]:
            raise HTTPException(
                status_code=400,
                detail=f"退款金额不可超过已付定金 {_fen_to_yuan_str(target_pay['amount_fen'])}",
            )
        target_pay["payment_status"] = "refunded"
        target_pay["refund_amount_fen"] = body.amount_fen
        target_pay["refunded_at"] = now_str
        target_pay["updated_at"] = now_str
        order["deposit_status"] = "unpaid"
        order["payment_status"] = "refunded" if order["balance_status"] == "unpaid" else "deposit_paid"
        order["updated_at"] = now_str

    elif body.refund_type == "balance":
        if order["payment_status"] != "fully_paid":
            raise HTTPException(
                status_code=400,
                detail="仅全额支付状态下可退尾款",
            )
        balance_pays = [p for p in payments
                        if p["payment_stage"] == "balance" and p["payment_status"] == "paid"]
        if not balance_pays:
            raise HTTPException(status_code=400, detail="未找到有效尾款支付记录")
        target_pay = balance_pays[-1]
        if body.amount_fen > target_pay["amount_fen"]:
            raise HTTPException(
                status_code=400,
                detail=f"退款金额不可超过已付尾款 {_fen_to_yuan_str(target_pay['amount_fen'])}",
            )
        target_pay["payment_status"] = "refunded"
        target_pay["refund_amount_fen"] = body.amount_fen
        target_pay["refunded_at"] = now_str
        target_pay["updated_at"] = now_str
        order["balance_status"] = "unpaid"
        order["payment_status"] = "deposit_paid"
        order["updated_at"] = now_str

    elif body.refund_type == "full":
        if order["payment_status"] not in ("deposit_paid", "fully_paid"):
            raise HTTPException(
                status_code=400,
                detail="当前支付状态不允许全额退款",
            )
        # 退所有已付款项
        refunded_total = 0
        for pay in payments:
            if pay["payment_status"] == "paid":
                pay["payment_status"] = "refunded"
                pay["refund_amount_fen"] = pay["amount_fen"]
                pay["refunded_at"] = now_str
                pay["updated_at"] = now_str
                refunded_total += pay["amount_fen"]
        order["deposit_status"] = "unpaid"
        order["balance_status"] = "unpaid"
        order["payment_status"] = "refunded"
        order["updated_at"] = now_str

        logger.info(
            "banquet_payment.full_refunded",
            order_id=order_id,
            refunded_total=refunded_total,
            tenant_id=tenant_id,
        )

    else:
        raise HTTPException(status_code=400, detail="无效的退款类型")

    return _ok({"order": order, "payments": payments})


# ─── 9. 支付凭证 ─────────────────────────────────────────────────────────────

@router.get("/orders/{order_id}/receipt")
async def get_receipt(order_id: str, request: Request):
    """
    获取支付凭证。
    返回定金收据 + 尾款收据的格式化文本，可用于前端打印/分享。
    """
    tenant_id = _get_tenant_id(request)
    order = MOCK_BANQUET_ORDERS.get(order_id)
    if not order or order["is_deleted"] or order["tenant_id"] != tenant_id:
        return _err("订单不存在", "NOT_FOUND")

    payments = MOCK_PAYMENTS.get(order_id, [])

    receipts = []
    for pay in payments:
        if pay["payment_status"] in ("paid", "refunded"):
            receipts.append(_build_receipt_summary(order, pay))

    return _ok({
        "order_id": order_id,
        "contact_name": order["contact_name"],
        "banquet_date": order["banquet_date"],
        "total_fen": order["total_fen"],
        "payment_status": order["payment_status"],
        "receipts": receipts,
    })


# ─── 10. 月度统计 ─────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(request: Request, year: int = 2026, month: int = 4):
    """
    宴席预订月度统计。
    返回：预订数/定金收入/尾款收入/取消率 + 各状态分布。
    """
    tenant_id = _get_tenant_id(request)

    orders = [
        o for o in MOCK_BANQUET_ORDERS.values()
        if not o["is_deleted"] and o["tenant_id"] == tenant_id
    ]

    month_prefix = f"{year:04d}-{month:02d}"
    month_orders = [o for o in orders if o["banquet_date"].startswith(month_prefix)]

    total_count = len(month_orders)
    cancelled_count = sum(1 for o in month_orders if o["status"] == "cancelled")
    deposit_paid_count = sum(
        1 for o in month_orders if o["payment_status"] in ("deposit_paid", "fully_paid")
    )
    fully_paid_count = sum(1 for o in month_orders if o["payment_status"] == "fully_paid")
    unpaid_count = sum(1 for o in month_orders if o["payment_status"] == "unpaid")

    # 统计实收定金/尾款（已付款项）
    all_month_pay_ids = {o["id"] for o in month_orders}
    deposit_income = 0
    balance_income = 0
    for oid, pays in MOCK_PAYMENTS.items():
        if oid not in all_month_pay_ids:
            continue
        for p in pays:
            if p["payment_status"] == "paid":
                if p["payment_stage"] == "deposit":
                    deposit_income += p["amount_fen"]
                elif p["payment_stage"] == "balance":
                    balance_income += p["amount_fen"]

    cancel_rate = round(cancelled_count / total_count, 4) if total_count > 0 else 0.0

    return _ok({
        "year": year,
        "month": month,
        "total_count": total_count,
        "cancelled_count": cancelled_count,
        "cancel_rate": cancel_rate,
        "deposit_paid_count": deposit_paid_count,
        "fully_paid_count": fully_paid_count,
        "unpaid_count": unpaid_count,
        "deposit_income_fen": deposit_income,
        "balance_income_fen": balance_income,
        "total_income_fen": deposit_income + balance_income,
    })


# ─── 内部辅助 ─────────────────────────────────────────────────────────────────

def _build_receipt_summary(order: dict, payment: dict) -> dict:
    """生成支付凭证摘要（可用于小票打印）。"""
    stage_label = {
        "deposit": "定金收据",
        "balance": "尾款收据",
        "full": "全额收据",
    }.get(payment["payment_stage"], "支付凭证")

    method_label = {
        "wechat": "微信支付",
        "alipay": "支付宝",
        "cash": "现金",
        "card": "刷卡",
        "transfer": "对公转账",
    }.get(payment.get("payment_method", ""), "其他")

    status_label = "已支付" if payment["payment_status"] == "paid" else "已退款"

    lines = [
        f"═══════ 屯象宴席 {stage_label} ═══════",
        f"预订编号：{order['id']}",
        f"预订人  ：{order.get('contact_name', '')}",
        f"宴席日期：{order['banquet_date']} {order.get('banquet_time', '')}",
        f"宾客人数：{order.get('guest_count', 0)} 人",
        f"─────────────────────────────────",
        f"总金额  ：{_fen_to_yuan_str(order['total_fen'])}",
        f"本次金额：{_fen_to_yuan_str(payment['amount_fen'])}",
        f"支付方式：{method_label}",
        f"状    态：{status_label}",
    ]
    if payment.get("transaction_id"):
        lines.append(f"流水号  ：{payment['transaction_id']}")
    if payment.get("paid_at"):
        lines.append(f"支付时间：{payment['paid_at']}")
    if payment["payment_status"] == "refunded" and payment.get("refunded_at"):
        lines.append(f"退款金额：{_fen_to_yuan_str(payment['refund_amount_fen'])}")
        lines.append(f"退款时间：{payment['refunded_at']}")
    lines.append("═══════════════════════════════════")

    return {
        "stage": payment["payment_stage"],
        "stage_label": stage_label,
        "amount_fen": payment["amount_fen"],
        "method_label": method_label,
        "status": payment["payment_status"],
        "paid_at": payment.get("paid_at"),
        "transaction_id": payment.get("transaction_id"),
        "text_lines": lines,
        "text": "\n".join(lines),
    }
