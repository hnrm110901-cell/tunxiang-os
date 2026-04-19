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
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/trade/banquet", tags=["banquet-order-payment"])


# ─── 依赖注入 ─────────────────────────────────────────────────────────────────


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _tid(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    return x_tenant_id


# ─── 工具函数 ────────────────────────────────────────────────────────────────


def _ok(data: object) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: str = "BAD_REQUEST") -> dict:
    return {"ok": False, "data": None, "error": {"code": code, "message": msg}}


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="Missing X-Tenant-ID")
    return tid


def _fen_to_yuan_str(fen: int) -> str:
    """将分转为"¥元"字符串，用于凭证展示。"""
    yuan = Decimal(fen) / Decimal(100)
    return f"¥{yuan:.2f}"


def _serialize_order(row: dict) -> dict:
    """将数据库行中的特殊类型转换为 JSON 可序列化格式。"""
    out = {}
    for k, v in row.items():
        if isinstance(v, uuid.UUID):
            out[k] = str(v)
        elif isinstance(v, (datetime, date, time)):
            out[k] = v.isoformat()
        elif isinstance(v, Decimal):
            out[k] = str(v)
        else:
            out[k] = v
    return out


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
    banquet_date: Optional[str] = None,
    payment_status: Optional[str] = None,
    store_id: Optional[str] = None,
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    """宴席订单列表，支持日期/支付状态/门店过滤。"""
    conditions = ["is_deleted = FALSE"]
    params: dict = {"offset": (page - 1) * size, "limit": size}

    if banquet_date:
        conditions.append("banquet_date = :banquet_date")
        params["banquet_date"] = banquet_date
    if payment_status:
        conditions.append("payment_status = :payment_status")
        params["payment_status"] = payment_status
    if store_id:
        conditions.append("store_id = :store_id::UUID")
        params["store_id"] = store_id

    where = " AND ".join(conditions)

    try:
        count_r = await db.execute(
            text(f"SELECT COUNT(*) FROM banquet_orders WHERE {where}"),
            params,
        )
        total: int = count_r.scalar() or 0

        rows_r = await db.execute(
            text(f"SELECT * FROM banquet_orders WHERE {where} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
            params,
        )
        items = [_serialize_order(dict(r)) for r in rows_r.mappings()]
    except SQLAlchemyError:
        logger.exception("banquet_order.list_orders.db_error", tenant_id=tenant_id)
        items = []
        total = 0

    return _ok({"items": items, "total": total, "page": page, "size": size})


# ─── 2. 宴席订单详情 ──────────────────────────────────────────────────────────


@router.get("/orders/{order_id}")
async def get_order(
    order_id: str,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    """宴席订单详情，含支付记录列表。"""
    try:
        order_r = await db.execute(
            text("SELECT * FROM banquet_orders WHERE id = :oid::UUID AND is_deleted = FALSE"),
            {"oid": order_id},
        )
        row = order_r.mappings().first()
    except SQLAlchemyError:
        logger.exception("banquet_order.get_order.db_error", order_id=order_id, tenant_id=tenant_id)
        return _err("数据库查询失败", "DB_ERROR")

    if not row:
        return _err("订单不存在", "NOT_FOUND")

    order = _serialize_order(dict(row))

    try:
        pays_r = await db.execute(
            text("SELECT * FROM banquet_payments WHERE banquet_order_id = :oid::UUID ORDER BY created_at ASC"),
            {"oid": order_id},
        )
        payments = [_serialize_order(dict(p)) for p in pays_r.mappings()]
    except SQLAlchemyError:
        logger.exception("banquet_order.get_order.payments_db_error", order_id=order_id, tenant_id=tenant_id)
        payments = []

    return _ok({**order, "payments": payments})


# ─── 3. 创建宴席预订 ──────────────────────────────────────────────────────────


@router.post("/orders")
async def create_order(
    body: CreateOrderReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    """
    创建宴席预订。
    deposit_fen = total_fen × deposit_rate（四舍五入到分），
    balance_fen = total_fen − deposit_fen。
    """
    deposit_fen = round(body.total_fen * body.deposit_rate)
    balance_fen = body.total_fen - deposit_fen
    order_id = str(uuid.uuid4())

    import json

    try:
        result = await db.execute(
            text("""
                INSERT INTO banquet_orders (
                    id, tenant_id, store_id,
                    contact_name, contact_phone,
                    banquet_date, banquet_time,
                    guest_count, table_ids,
                    total_fen, deposit_rate, deposit_fen, balance_fen,
                    deposit_status, balance_status, payment_status,
                    status, notes,
                    cancel_reason, cancelled_at, is_deleted
                ) VALUES (
                    :id::UUID, :tenant_id::UUID, :store_id::UUID,
                    :contact_name, :contact_phone,
                    :banquet_date::DATE, :banquet_time::TIME,
                    :guest_count, :table_ids::JSONB,
                    :total_fen, :deposit_rate, :deposit_fen, :balance_fen,
                    'unpaid', 'unpaid', 'unpaid',
                    'pending', :notes,
                    NULL, NULL, FALSE
                )
                RETURNING *
            """),
            {
                "id": order_id,
                "tenant_id": tenant_id,
                "store_id": body.store_id,
                "contact_name": body.contact_name,
                "contact_phone": body.contact_phone,
                "banquet_date": body.banquet_date,
                "banquet_time": body.banquet_time,
                "guest_count": body.guest_count,
                "table_ids": json.dumps(body.table_ids),
                "total_fen": body.total_fen,
                "deposit_rate": str(body.deposit_rate),
                "deposit_fen": deposit_fen,
                "balance_fen": balance_fen,
                "notes": body.notes,
            },
        )
        await db.commit()
        row = result.mappings().first()
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("banquet_order.create_order.db_error", tenant_id=tenant_id)
        raise HTTPException(status_code=503, detail="数据库写入失败，请稍后重试")

    order = _serialize_order(dict(row))
    logger.info(
        "banquet_order.created",
        order_id=order_id,
        tenant_id=tenant_id,
        total_fen=body.total_fen,
        deposit_fen=deposit_fen,
    )
    return _ok(order)


# ─── 4. 更新预订信息 ──────────────────────────────────────────────────────────


@router.put("/orders/{order_id}")
async def update_order(
    order_id: str,
    body: UpdateOrderReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    """
    更新预订信息。仅允许在未支付（payment_status=unpaid）或只付了定金时修改。
    若已全额支付则不可修改。
    """
    try:
        order_r = await db.execute(
            text("SELECT * FROM banquet_orders WHERE id = :oid::UUID AND is_deleted = FALSE"),
            {"oid": order_id},
        )
        row = order_r.mappings().first()
    except SQLAlchemyError:
        logger.exception("banquet_order.update_order.db_error", order_id=order_id, tenant_id=tenant_id)
        raise HTTPException(status_code=503, detail="数据库查询失败")

    if not row:
        return _err("订单不存在", "NOT_FOUND")

    order = dict(row)
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

    if not updates:
        return _ok(_serialize_order(order))

    set_clauses = []
    params: dict = {"oid": order_id}
    for field, val in updates.items():
        set_clauses.append(f"{field} = :{field}")
        params[field] = val
    set_clauses.append("updated_at = NOW()")

    try:
        result = await db.execute(
            text(f"UPDATE banquet_orders SET {', '.join(set_clauses)} WHERE id = :oid::UUID RETURNING *"),
            params,
        )
        await db.commit()
        updated_row = result.mappings().first()
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("banquet_order.update_order.write_error", order_id=order_id, tenant_id=tenant_id)
        raise HTTPException(status_code=503, detail="数据库写入失败，请稍后重试")

    logger.info("banquet_order.updated", order_id=order_id, tenant_id=tenant_id)
    return _ok(_serialize_order(dict(updated_row)))


# ─── 5. 取消预订 ─────────────────────────────────────────────────────────────


@router.post("/orders/{order_id}/cancel")
async def cancel_order(
    order_id: str,
    body: CancelOrderReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    """
    取消预订。
    - 未支付：直接取消。
    - 已付定金（balance_status=unpaid）：需先退定金，本接口仅标记取消，
      退款通过 /refund 端点处理。
    - 已全额支付：不允许直接取消，须走退款流程再取消。
    """
    try:
        order_r = await db.execute(
            text("SELECT * FROM banquet_orders WHERE id = :oid::UUID AND is_deleted = FALSE"),
            {"oid": order_id},
        )
        row = order_r.mappings().first()
    except SQLAlchemyError:
        logger.exception("banquet_order.cancel_order.db_error", order_id=order_id, tenant_id=tenant_id)
        raise HTTPException(status_code=503, detail="数据库查询失败")

    if not row:
        return _err("订单不存在", "NOT_FOUND")

    order = dict(row)
    if order["status"] == "cancelled":
        return _err("订单已取消", "ALREADY_CANCELLED")

    if order["payment_status"] == "fully_paid":
        raise HTTPException(
            status_code=400,
            detail="已全额支付的订单请先完成退款，再取消预订",
        )

    try:
        result = await db.execute(
            text("""
                UPDATE banquet_orders
                SET status = 'cancelled',
                    cancel_reason = :reason,
                    cancelled_at = NOW(),
                    updated_at = NOW()
                WHERE id = :oid::UUID
                RETURNING *
            """),
            {"oid": order_id, "reason": body.cancel_reason},
        )
        await db.commit()
        updated_row = result.mappings().first()
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("banquet_order.cancel_order.write_error", order_id=order_id, tenant_id=tenant_id)
        raise HTTPException(status_code=503, detail="数据库写入失败，请稍后重试")

    logger.info("banquet_order.cancelled", order_id=order_id, reason=body.cancel_reason, tenant_id=tenant_id)
    return _ok(_serialize_order(dict(updated_row)))


# ─── 6. 支付定金 ─────────────────────────────────────────────────────────────


@router.post("/orders/{order_id}/pay-deposit")
async def pay_deposit(
    order_id: str,
    body: PayDepositReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    """
    支付定金。

    状态机规则：
    - deposit_status 必须是 unpaid（不重复收定金）
    - amount_fen 必须 >= deposit_fen（不允许欠付定金）
    - 若 amount_fen >= total_fen，视为全额支付，同时更新 balance_status=paid
    - 返回：更新后的订单状态 + 支付凭证
    """
    try:
        order_r = await db.execute(
            text("SELECT * FROM banquet_orders WHERE id = :oid::UUID AND is_deleted = FALSE"),
            {"oid": order_id},
        )
        row = order_r.mappings().first()
    except SQLAlchemyError:
        logger.exception("banquet_order.pay_deposit.db_error", order_id=order_id, tenant_id=tenant_id)
        raise HTTPException(status_code=503, detail="数据库查询失败")

    if not row:
        return _err("订单不存在", "NOT_FOUND")

    order = dict(row)
    if order["status"] == "cancelled":
        raise HTTPException(status_code=400, detail="订单已取消，不可支付")

    if order["deposit_status"] == "paid":
        raise HTTPException(status_code=400, detail="定金已支付，请勿重复操作")

    deposit_fen: int = order["deposit_fen"]
    if body.amount_fen < deposit_fen:
        raise HTTPException(
            status_code=400,
            detail=(
                f"支付金额不足：应付定金 {_fen_to_yuan_str(deposit_fen)}，实付 {_fen_to_yuan_str(body.amount_fen)}"
            ),
        )

    pay_id = str(uuid.uuid4())
    total_fen: int = order["total_fen"]

    # 状态机：全额支付判断
    if body.amount_fen >= total_fen:
        new_balance_status = "paid"
        new_payment_status = "fully_paid"
    else:
        new_balance_status = "unpaid"
        new_payment_status = "deposit_paid"

    try:
        pay_r = await db.execute(
            text("""
                INSERT INTO banquet_payments (
                    id, tenant_id, banquet_order_id,
                    payment_stage, amount_fen, payment_method,
                    payment_status, transaction_id, paid_at,
                    refund_amount_fen, refunded_at, operator_id, notes
                ) VALUES (
                    :id::UUID, :tenant_id::UUID, :banquet_order_id::UUID,
                    'deposit', :amount_fen, :payment_method,
                    'paid', :transaction_id, NOW(),
                    0, NULL, NULL, :notes
                )
                RETURNING *
            """),
            {
                "id": pay_id,
                "tenant_id": tenant_id,
                "banquet_order_id": order_id,
                "amount_fen": body.amount_fen,
                "payment_method": body.payment_method,
                "transaction_id": body.transaction_id,
                "notes": body.notes,
            },
        )
        order_r2 = await db.execute(
            text("""
                UPDATE banquet_orders
                SET deposit_status = 'paid',
                    balance_status = :balance_status,
                    payment_status = :payment_status,
                    updated_at = NOW()
                WHERE id = :oid::UUID
                RETURNING *
            """),
            {
                "oid": order_id,
                "balance_status": new_balance_status,
                "payment_status": new_payment_status,
            },
        )
        await db.commit()
        payment_rec = _serialize_order(dict(pay_r.mappings().first()))
        updated_order = _serialize_order(dict(order_r2.mappings().first()))
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("banquet_order.pay_deposit.write_error", order_id=order_id, tenant_id=tenant_id)
        raise HTTPException(status_code=503, detail="数据库写入失败，请稍后重试")

    logger.info(
        "banquet_payment.deposit_paid",
        order_id=order_id,
        amount_fen=body.amount_fen,
        payment_status=new_payment_status,
        tenant_id=tenant_id,
    )
    return _ok(
        {
            "order": updated_order,
            "payment": payment_rec,
            "receipt_summary": _build_receipt_summary(updated_order, payment_rec),
        }
    )


# ─── 7. 支付尾款 ─────────────────────────────────────────────────────────────


@router.post("/orders/{order_id}/pay-balance")
async def pay_balance(
    order_id: str,
    body: PayBalanceReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    """
    支付尾款。

    状态机规则：
    - 前置检查：deposit_status 必须是 paid（定金未付不得支付尾款）
    - balance_status 必须是 unpaid（不重复收尾款）
    - amount_fen 必须 >= balance_fen
    - 成功后：payment_status=fully_paid, balance_status=paid
    """
    try:
        order_r = await db.execute(
            text("SELECT * FROM banquet_orders WHERE id = :oid::UUID AND is_deleted = FALSE"),
            {"oid": order_id},
        )
        row = order_r.mappings().first()
    except SQLAlchemyError:
        logger.exception("banquet_order.pay_balance.db_error", order_id=order_id, tenant_id=tenant_id)
        raise HTTPException(status_code=503, detail="数据库查询失败")

    if not row:
        return _err("订单不存在", "NOT_FOUND")

    order = dict(row)
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
                f"支付金额不足：应付尾款 {_fen_to_yuan_str(balance_fen)}，实付 {_fen_to_yuan_str(body.amount_fen)}"
            ),
        )

    pay_id = str(uuid.uuid4())

    try:
        pay_r = await db.execute(
            text("""
                INSERT INTO banquet_payments (
                    id, tenant_id, banquet_order_id,
                    payment_stage, amount_fen, payment_method,
                    payment_status, transaction_id, paid_at,
                    refund_amount_fen, refunded_at, operator_id, notes
                ) VALUES (
                    :id::UUID, :tenant_id::UUID, :banquet_order_id::UUID,
                    'balance', :amount_fen, :payment_method,
                    'paid', :transaction_id, NOW(),
                    0, NULL, NULL, :notes
                )
                RETURNING *
            """),
            {
                "id": pay_id,
                "tenant_id": tenant_id,
                "banquet_order_id": order_id,
                "amount_fen": body.amount_fen,
                "payment_method": body.payment_method,
                "transaction_id": body.transaction_id,
                "notes": body.notes,
            },
        )
        order_r2 = await db.execute(
            text("""
                UPDATE banquet_orders
                SET balance_status = 'paid',
                    payment_status = 'fully_paid',
                    updated_at = NOW()
                WHERE id = :oid::UUID
                RETURNING *
            """),
            {"oid": order_id},
        )
        # 取全部支付记录（含刚插入的）
        all_pays_r = await db.execute(
            text("SELECT * FROM banquet_payments WHERE banquet_order_id = :oid::UUID ORDER BY created_at ASC"),
            {"oid": order_id},
        )
        await db.commit()
        payment_rec = _serialize_order(dict(pay_r.mappings().first()))
        updated_order = _serialize_order(dict(order_r2.mappings().first()))
        all_payments = [_serialize_order(dict(p)) for p in all_pays_r.mappings()]
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("banquet_order.pay_balance.write_error", order_id=order_id, tenant_id=tenant_id)
        raise HTTPException(status_code=503, detail="数据库写入失败，请稍后重试")

    logger.info(
        "banquet_payment.balance_paid",
        order_id=order_id,
        amount_fen=body.amount_fen,
        tenant_id=tenant_id,
    )
    return _ok(
        {
            "order": updated_order,
            "payment": payment_rec,
            "all_payments": all_payments,
        }
    )


# ─── 8. 退款 ─────────────────────────────────────────────────────────────────


@router.post("/orders/{order_id}/refund")
async def refund_payment(
    order_id: str,
    body: RefundReq,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
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
    try:
        order_r = await db.execute(
            text("SELECT * FROM banquet_orders WHERE id = :oid::UUID AND is_deleted = FALSE"),
            {"oid": order_id},
        )
        order_row = order_r.mappings().first()
    except SQLAlchemyError:
        logger.exception("banquet_order.refund.db_error", order_id=order_id, tenant_id=tenant_id)
        raise HTTPException(status_code=503, detail="数据库查询失败")

    if not order_row:
        return _err("订单不存在", "NOT_FOUND")

    order = dict(order_row)

    try:
        pays_r = await db.execute(
            text("SELECT * FROM banquet_payments WHERE banquet_order_id = :oid::UUID ORDER BY created_at ASC"),
            {"oid": order_id},
        )
        payments = [dict(p) for p in pays_r.mappings()]
    except SQLAlchemyError:
        logger.exception("banquet_order.refund.payments_error", order_id=order_id, tenant_id=tenant_id)
        raise HTTPException(status_code=503, detail="数据库查询失败")

    try:
        if body.refund_type == "deposit":
            if order["deposit_status"] != "paid":
                raise HTTPException(status_code=400, detail="定金尚未支付，无法退款")
            if order["balance_status"] == "paid":
                raise HTTPException(
                    status_code=400,
                    detail="已全额支付，不可仅退定金，请使用 refund_type=full 申请全额退款",
                )
            deposit_pays = [p for p in payments if p["payment_stage"] == "deposit" and p["payment_status"] == "paid"]
            if not deposit_pays:
                raise HTTPException(status_code=400, detail="未找到有效定金支付记录")
            target_pay = deposit_pays[-1]
            if body.amount_fen > target_pay["amount_fen"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"退款金额不可超过已付定金 {_fen_to_yuan_str(target_pay['amount_fen'])}",
                )
            await db.execute(
                text("""
                    UPDATE banquet_payments
                    SET payment_status = 'refunded',
                        refund_amount_fen = :refund_fen,
                        refunded_at = NOW(),
                        updated_at = NOW()
                    WHERE id = :pid::UUID
                """),
                {"pid": str(target_pay["id"]), "refund_fen": body.amount_fen},
            )
            new_payment_status = "refunded" if order["balance_status"] == "unpaid" else "deposit_paid"
            order_result = await db.execute(
                text("""
                    UPDATE banquet_orders
                    SET deposit_status = 'unpaid',
                        payment_status = :payment_status,
                        updated_at = NOW()
                    WHERE id = :oid::UUID
                    RETURNING *
                """),
                {"oid": order_id, "payment_status": new_payment_status},
            )

        elif body.refund_type == "balance":
            if order["payment_status"] != "fully_paid":
                raise HTTPException(
                    status_code=400,
                    detail="仅全额支付状态下可退尾款",
                )
            balance_pays = [p for p in payments if p["payment_stage"] == "balance" and p["payment_status"] == "paid"]
            if not balance_pays:
                raise HTTPException(status_code=400, detail="未找到有效尾款支付记录")
            target_pay = balance_pays[-1]
            if body.amount_fen > target_pay["amount_fen"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"退款金额不可超过已付尾款 {_fen_to_yuan_str(target_pay['amount_fen'])}",
                )
            await db.execute(
                text("""
                    UPDATE banquet_payments
                    SET payment_status = 'refunded',
                        refund_amount_fen = :refund_fen,
                        refunded_at = NOW(),
                        updated_at = NOW()
                    WHERE id = :pid::UUID
                """),
                {"pid": str(target_pay["id"]), "refund_fen": body.amount_fen},
            )
            order_result = await db.execute(
                text("""
                    UPDATE banquet_orders
                    SET balance_status = 'unpaid',
                        payment_status = 'deposit_paid',
                        updated_at = NOW()
                    WHERE id = :oid::UUID
                    RETURNING *
                """),
                {"oid": order_id},
            )

        elif body.refund_type == "full":
            if order["payment_status"] not in ("deposit_paid", "fully_paid"):
                raise HTTPException(
                    status_code=400,
                    detail="当前支付状态不允许全额退款",
                )
            paid_ids = [str(p["id"]) for p in payments if p["payment_status"] == "paid"]
            if paid_ids:
                await db.execute(
                    text("""
                        UPDATE banquet_payments
                        SET payment_status = 'refunded',
                            refund_amount_fen = amount_fen,
                            refunded_at = NOW(),
                            updated_at = NOW()
                        WHERE id = ANY(:ids::UUID[])
                    """),
                    {"ids": paid_ids},
                )
            refunded_total = sum(p["amount_fen"] for p in payments if p["payment_status"] == "paid")
            order_result = await db.execute(
                text("""
                    UPDATE banquet_orders
                    SET deposit_status = 'unpaid',
                        balance_status = 'unpaid',
                        payment_status = 'refunded',
                        updated_at = NOW()
                    WHERE id = :oid::UUID
                    RETURNING *
                """),
                {"oid": order_id},
            )
            logger.info(
                "banquet_payment.full_refunded",
                order_id=order_id,
                refunded_total=refunded_total,
                tenant_id=tenant_id,
            )

        else:
            raise HTTPException(status_code=400, detail="无效的退款类型")

        # 读取最新支付记录
        final_pays_r = await db.execute(
            text("SELECT * FROM banquet_payments WHERE banquet_order_id = :oid::UUID ORDER BY created_at ASC"),
            {"oid": order_id},
        )
        await db.commit()
        updated_order = _serialize_order(dict(order_result.mappings().first()))
        final_payments = [_serialize_order(dict(p)) for p in final_pays_r.mappings()]

    except HTTPException:
        await db.rollback()
        raise
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("banquet_order.refund.write_error", order_id=order_id, tenant_id=tenant_id)
        raise HTTPException(status_code=503, detail="数据库写入失败，请稍后重试")

    return _ok({"order": updated_order, "payments": final_payments})


# ─── 9. 支付凭证 ─────────────────────────────────────────────────────────────


@router.get("/orders/{order_id}/receipt")
async def get_receipt(
    order_id: str,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    """
    获取支付凭证。
    返回定金收据 + 尾款收据的格式化文本，可用于前端打印/分享。
    """
    try:
        order_r = await db.execute(
            text("SELECT * FROM banquet_orders WHERE id = :oid::UUID AND is_deleted = FALSE"),
            {"oid": order_id},
        )
        row = order_r.mappings().first()
    except SQLAlchemyError:
        logger.exception("banquet_order.get_receipt.db_error", order_id=order_id, tenant_id=tenant_id)
        return _err("数据库查询失败", "DB_ERROR")

    if not row:
        return _err("订单不存在", "NOT_FOUND")

    order = _serialize_order(dict(row))

    try:
        pays_r = await db.execute(
            text("SELECT * FROM banquet_payments WHERE banquet_order_id = :oid::UUID ORDER BY created_at ASC"),
            {"oid": order_id},
        )
        payments = [_serialize_order(dict(p)) for p in pays_r.mappings()]
    except SQLAlchemyError:
        logger.exception("banquet_order.get_receipt.payments_error", order_id=order_id, tenant_id=tenant_id)
        payments = []

    receipts = []
    for pay in payments:
        if pay["payment_status"] in ("paid", "refunded"):
            receipts.append(_build_receipt_summary(order, pay))

    return _ok(
        {
            "order_id": order_id,
            "contact_name": order["contact_name"],
            "banquet_date": order["banquet_date"],
            "total_fen": order["total_fen"],
            "payment_status": order["payment_status"],
            "receipts": receipts,
        }
    )


# ─── 10. 月度统计 ─────────────────────────────────────────────────────────────


@router.get("/stats")
async def get_stats(
    year: int = 2026,
    month: int = 4,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    """
    宴席预订月度统计。
    返回：预订数/定金收入/尾款收入/取消率 + 各状态分布。
    """
    month_start = f"{year:04d}-{month:02d}-01"
    # 次月第一天作为上限（不含）
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    month_end = f"{next_year:04d}-{next_month:02d}-01"

    try:
        stats_r = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS total_count,
                    COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled_count,
                    COUNT(*) FILTER (WHERE payment_status IN ('deposit_paid', 'fully_paid')) AS deposit_paid_count,
                    COUNT(*) FILTER (WHERE payment_status = 'fully_paid') AS fully_paid_count,
                    COUNT(*) FILTER (WHERE payment_status = 'unpaid') AS unpaid_count
                FROM banquet_orders
                WHERE is_deleted = FALSE
                  AND banquet_date >= :month_start::DATE
                  AND banquet_date < :month_end::DATE
            """),
            {"month_start": month_start, "month_end": month_end},
        )
        stats_row = stats_r.mappings().first()

        income_r = await db.execute(
            text("""
                SELECT
                    COALESCE(SUM(bp.amount_fen) FILTER (WHERE bp.payment_stage = 'deposit'), 0) AS deposit_income,
                    COALESCE(SUM(bp.amount_fen) FILTER (WHERE bp.payment_stage = 'balance'), 0) AS balance_income
                FROM banquet_payments bp
                JOIN banquet_orders bo ON bp.banquet_order_id = bo.id
                WHERE bp.payment_status = 'paid'
                  AND bo.is_deleted = FALSE
                  AND bo.banquet_date >= :month_start::DATE
                  AND bo.banquet_date < :month_end::DATE
            """),
            {"month_start": month_start, "month_end": month_end},
        )
        income_row = income_r.mappings().first()

    except SQLAlchemyError:
        logger.exception("banquet_order.get_stats.db_error", tenant_id=tenant_id)
        return _ok(
            {
                "year": year,
                "month": month,
                "total_count": 0,
                "cancelled_count": 0,
                "cancel_rate": 0.0,
                "deposit_paid_count": 0,
                "fully_paid_count": 0,
                "unpaid_count": 0,
                "deposit_income_fen": 0,
                "balance_income_fen": 0,
                "total_income_fen": 0,
            }
        )

    total_count = int(stats_row["total_count"] or 0)
    cancelled_count = int(stats_row["cancelled_count"] or 0)
    deposit_income = int(income_row["deposit_income"] or 0)
    balance_income = int(income_row["balance_income"] or 0)
    cancel_rate = round(cancelled_count / total_count, 4) if total_count > 0 else 0.0

    return _ok(
        {
            "year": year,
            "month": month,
            "total_count": total_count,
            "cancelled_count": cancelled_count,
            "cancel_rate": cancel_rate,
            "deposit_paid_count": int(stats_row["deposit_paid_count"] or 0),
            "fully_paid_count": int(stats_row["fully_paid_count"] or 0),
            "unpaid_count": int(stats_row["unpaid_count"] or 0),
            "deposit_income_fen": deposit_income,
            "balance_income_fen": balance_income,
            "total_income_fen": deposit_income + balance_income,
        }
    )


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
        "─────────────────────────────────",
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
