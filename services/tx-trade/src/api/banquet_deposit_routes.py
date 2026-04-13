"""宴会定金抵扣 API — 场次维度定金管理

注意：现有 banquet_payment_routes.py 以 banquet_id（预订单）为维度管理微信支付定金，
本模块以 session_id（宴席场次）为维度管理门店收银端定金，二者互补不重复。

端点：
  POST /api/v1/banquet/deposits              — 收取宴会定金（关联 session_id）
  GET  /api/v1/banquet/deposits/{session_id} — 查询场次定金余额
  POST /api/v1/banquet/deposits/{session_id}/apply  — 结账时抵扣定金（返回剩余应付）
  POST /api/v1/banquet/deposits/{session_id}/refund — 退定金
"""
import asyncio
import uuid
from datetime import date, datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import DepositEventType
from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/banquet/deposits", tags=["宴会定金抵扣"])


# ─── 依赖注入 ────────────────────────────────────────────────────────────────

async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _tid(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    return x_tenant_id


# ─── 请求模型 ─────────────────────────────────────────────────────────────────

class DepositCreateRequest(BaseModel):
    session_id: str = Field(..., description="宴席场次 ID")
    amount_fen: int = Field(..., gt=0, description="收取金额（分）")
    payment_method: str = Field("cash", description="cash/wechat/alipay/bank_transfer")
    operator_id: Optional[str] = Field(None, description="操作员 ID")
    notes: Optional[str] = Field(None, max_length=200)


class DepositApplyRequest(BaseModel):
    apply_amount_fen: int = Field(..., gt=0, description="本次抵扣金额（分），0 = 全额抵扣")
    order_total_fen: int = Field(..., gt=0, description="结账总金额（分）")
    operator_id: Optional[str] = Field(None)


class DepositRefundRequest(BaseModel):
    refund_amount_fen: int = Field(..., gt=0, description="退款金额（分）")
    refund_reason: str = Field(..., min_length=1, max_length=200)
    operator_id: Optional[str] = Field(None)


# ─── 工具 ─────────────────────────────────────────────────────────────────────

def _serialize(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, uuid.UUID):
            out[k] = str(v)
        elif isinstance(v, (datetime, date)):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


# ─── 收取定金 ────────────────────────────────────────────────────────────────

@router.post("", summary="收取宴会定金（关联 session_id）")
async def collect_deposit(
    body: DepositCreateRequest,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    """在 POS 端收取宴席场次定金，记录到 banquet_session_deposits 表。"""
    # 验证场次存在
    sess_r = await db.execute(
        text("SELECT id, status FROM banquet_sessions WHERE id = :sid::UUID AND is_deleted = FALSE"),
        {"sid": body.session_id},
    )
    sess = sess_r.mappings().first()
    if not sess:
        raise HTTPException(status_code=404, detail="场次不存在")
    if sess["status"] in ("completed", "cancelled"):
        raise HTTPException(status_code=400, detail=f"场次状态 {sess['status']} 不允许收取定金")

    now = datetime.now(timezone.utc)
    result = await db.execute(
        text("""
            INSERT INTO banquet_session_deposits
                (tenant_id, session_id, amount_fen, balance_fen, payment_method,
                 status, operator_id, notes, collected_at)
            VALUES
                (:tid::UUID, :sid::UUID, :amt, :amt, :pm, 'active',
                 :op, :notes, :now)
            RETURNING id, amount_fen, balance_fen, payment_method, status, collected_at
        """),
        {
            "tid": tenant_id,
            "sid": body.session_id,
            "amt": body.amount_fen,
            "pm": body.payment_method,
            "op": body.operator_id,
            "notes": body.notes,
            "now": now,
        },
    )
    row = _serialize(dict(result.mappings().first()))

    # 同步更新场次 deposit_fen 汇总字段
    await db.execute(
        text("""
            UPDATE banquet_sessions
            SET deposit_fen = COALESCE(deposit_fen, 0) + :amt,
                updated_at  = :now
            WHERE id = :sid::UUID
        """),
        {"amt": body.amount_fen, "now": now, "sid": body.session_id},
    )
    await db.commit()

    asyncio.create_task(
        emit_event(
            event_type=DepositEventType.COLLECTED,
            tenant_id=tenant_id,
            stream_id=body.session_id,
            payload={
                "deposit_id": row["id"],
                "session_id": body.session_id,
                "amount_fen": body.amount_fen,
                "payment_method": body.payment_method,
                "operator_id": body.operator_id,
            },
            source_service="tx-trade",
        )
    )

    logger.info(
        "banquet_deposit.collected",
        session_id=body.session_id,
        amount_fen=body.amount_fen,
        tenant_id=tenant_id,
    )
    return {"ok": True, "data": {"session_id": body.session_id, **row}}


# ─── 查询定金余额 ─────────────────────────────────────────────────────────────

@router.get("/{session_id}", summary="查询场次定金余额")
async def get_deposit_balance(
    session_id: str,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    """汇总该场次所有有效定金记录，返回总收取额和可用余额。"""
    # 验证场次
    sess_r = await db.execute(
        text("""
            SELECT id, contact_name, guest_count, status, total_amount_fen
            FROM banquet_sessions WHERE id = :sid::UUID AND is_deleted = FALSE
        """),
        {"sid": session_id},
    )
    sess = sess_r.mappings().first()
    if not sess:
        raise HTTPException(status_code=404, detail="场次不存在")

    # 汇总定金
    agg_r = await db.execute(
        text("""
            SELECT
                COALESCE(SUM(amount_fen), 0)  AS total_collected_fen,
                COALESCE(SUM(balance_fen), 0) AS total_balance_fen,
                COUNT(*) FILTER (WHERE status = 'active')  AS active_records,
                COUNT(*) FILTER (WHERE status = 'applied') AS applied_records,
                COUNT(*) FILTER (WHERE status = 'refunded') AS refunded_records
            FROM banquet_session_deposits
            WHERE session_id = :sid::UUID AND status != 'refunded'
        """),
        {"sid": session_id},
    )
    agg = dict(agg_r.mappings().first())

    # 明细列表
    detail_r = await db.execute(
        text("""
            SELECT id, amount_fen, balance_fen, payment_method, status,
                   collected_at, applied_at, notes
            FROM banquet_session_deposits
            WHERE session_id = :sid::UUID
            ORDER BY collected_at DESC
        """),
        {"sid": session_id},
    )
    records = [_serialize(dict(r)) for r in detail_r.mappings().all()]

    order_total = sess["total_amount_fen"] or 0
    balance = agg["total_balance_fen"]

    return {
        "ok": True,
        "data": {
            "session_id": session_id,
            "contact_name": sess["contact_name"],
            "session_status": sess["status"],
            "order_total_fen": order_total,
            "total_collected_fen": agg["total_collected_fen"],
            "total_balance_fen": balance,
            "remaining_payable_fen": max(0, order_total - balance),
            "records": records,
        },
    }


# ─── 结账抵扣定金 ─────────────────────────────────────────────────────────────

@router.post("/{session_id}/apply", summary="结账时抵扣定金（返回剩余应付）")
async def apply_deposit(
    session_id: str,
    body: DepositApplyRequest,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    """将场次有效定金余额抵扣结账金额，返回抵扣后的剩余应付金额。"""
    # 获取可用定金余额
    agg_r = await db.execute(
        text("""
            SELECT COALESCE(SUM(balance_fen), 0) AS total_balance_fen
            FROM banquet_session_deposits
            WHERE session_id = :sid::UUID AND status = 'active'
        """),
        {"sid": session_id},
    )
    total_balance = (agg_r.mappings().first() or {}).get("total_balance_fen", 0)

    if total_balance <= 0:
        raise HTTPException(status_code=400, detail="无可用定金余额")

    # 实际抵扣金额：不超过余额，不超过订单总额
    deduct = min(body.apply_amount_fen, total_balance, body.order_total_fen)
    remaining = body.order_total_fen - deduct
    now = datetime.now(timezone.utc)

    # 按收取时间先进先出地扣减各定金记录
    active_r = await db.execute(
        text("""
            SELECT id, balance_fen FROM banquet_session_deposits
            WHERE session_id = :sid::UUID AND status = 'active' AND balance_fen > 0
            ORDER BY collected_at ASC
        """),
        {"sid": session_id},
    )
    actives = list(active_r.mappings().all())

    left_to_deduct = deduct
    for dep_row in actives:
        if left_to_deduct <= 0:
            break
        dep_id = dep_row["id"]
        dep_balance = dep_row["balance_fen"]
        this_deduct = min(left_to_deduct, dep_balance)
        new_balance = dep_balance - this_deduct
        new_status = "applied" if new_balance == 0 else "active"

        await db.execute(
            text("""
                UPDATE banquet_session_deposits
                SET balance_fen = :bal,
                    status      = :st,
                    applied_at  = :now,
                    updated_at  = :now
                WHERE id = :did::UUID
            """),
            {"bal": new_balance, "st": new_status, "now": now, "did": str(dep_id)},
        )
        left_to_deduct -= this_deduct

    await db.commit()

    asyncio.create_task(
        emit_event(
            event_type=DepositEventType.APPLIED,
            tenant_id=tenant_id,
            stream_id=session_id,
            payload={
                "session_id": session_id,
                "order_total_fen": body.order_total_fen,
                "deducted_fen": deduct,
                "remaining_payable_fen": remaining,
                "operator_id": body.operator_id,
            },
            source_service="tx-trade",
        )
    )

    # 同步发 DEPOSIT.CONVERTED 事件（定金转收入）
    asyncio.create_task(
        emit_event(
            event_type=DepositEventType.CONVERTED_TO_REVENUE,
            tenant_id=tenant_id,
            stream_id=session_id,
            payload={
                "session_id": session_id,
                "converted_fen": deduct,
            },
            source_service="tx-trade",
        )
    )

    logger.info(
        "banquet_deposit.applied",
        session_id=session_id,
        deducted_fen=deduct,
        remaining_fen=remaining,
        tenant_id=tenant_id,
    )
    return {
        "ok": True,
        "data": {
            "session_id": session_id,
            "order_total_fen": body.order_total_fen,
            "deducted_fen": deduct,
            "remaining_payable_fen": remaining,
        },
    }


# ─── 退定金 ──────────────────────────────────────────────────────────────────

@router.post("/{session_id}/refund", summary="退定金")
async def refund_deposit(
    session_id: str,
    body: DepositRefundRequest,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    """退还场次定金余额（取消宴席/顾客申请退款场景）。"""
    # 获取可退余额
    agg_r = await db.execute(
        text("""
            SELECT COALESCE(SUM(balance_fen), 0) AS total_balance_fen
            FROM banquet_session_deposits
            WHERE session_id = :sid::UUID AND status = 'active'
        """),
        {"sid": session_id},
    )
    total_balance = (agg_r.mappings().first() or {}).get("total_balance_fen", 0)

    if total_balance <= 0:
        raise HTTPException(status_code=400, detail="无可退余额")
    if body.refund_amount_fen > total_balance:
        raise HTTPException(
            status_code=400,
            detail=f"退款金额 {body.refund_amount_fen} 分超过可退余额 {total_balance} 分",
        )

    now = datetime.now(timezone.utc)

    # 按先进先出退定金记录
    active_r = await db.execute(
        text("""
            SELECT id, balance_fen FROM banquet_session_deposits
            WHERE session_id = :sid::UUID AND status = 'active' AND balance_fen > 0
            ORDER BY collected_at ASC
        """),
        {"sid": session_id},
    )
    actives = list(active_r.mappings().all())

    left_to_refund = body.refund_amount_fen
    for dep_row in actives:
        if left_to_refund <= 0:
            break
        dep_id = dep_row["id"]
        dep_balance = dep_row["balance_fen"]
        this_refund = min(left_to_refund, dep_balance)
        new_balance = dep_balance - this_refund
        new_status = "refunded" if new_balance == 0 else "active"

        await db.execute(
            text("""
                UPDATE banquet_session_deposits
                SET balance_fen = :bal,
                    status      = :st,
                    updated_at  = :now
                WHERE id = :did::UUID
            """),
            {"bal": new_balance, "st": new_status, "now": now, "did": str(dep_id)},
        )
        left_to_refund -= this_refund

    # 同步更新场次 deposit_fen（减去退款金额）
    await db.execute(
        text("""
            UPDATE banquet_sessions
            SET deposit_fen = GREATEST(0, COALESCE(deposit_fen, 0) - :amt),
                updated_at  = :now
            WHERE id = :sid::UUID
        """),
        {"amt": body.refund_amount_fen, "now": now, "sid": session_id},
    )
    await db.commit()

    asyncio.create_task(
        emit_event(
            event_type=DepositEventType.REFUNDED,
            tenant_id=tenant_id,
            stream_id=session_id,
            payload={
                "session_id": session_id,
                "refund_amount_fen": body.refund_amount_fen,
                "refund_reason": body.refund_reason,
                "operator_id": body.operator_id,
            },
            source_service="tx-trade",
        )
    )

    logger.info(
        "banquet_deposit.refunded",
        session_id=session_id,
        refund_amount_fen=body.refund_amount_fen,
        tenant_id=tenant_id,
    )
    return {
        "ok": True,
        "data": {
            "session_id": session_id,
            "refunded_fen": body.refund_amount_fen,
            "refund_reason": body.refund_reason,
            "remaining_balance_fen": total_balance - body.refund_amount_fen,
        },
    }
