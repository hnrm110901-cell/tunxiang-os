"""储值充值 API — 完整生命周期

GET  /api/v1/members/{member_id}/stored-value
POST /api/v1/members/{member_id}/stored-value/recharge
POST /api/v1/members/{member_id}/stored-value/consume
POST /api/v1/members/{member_id}/stored-value/refund

充值赠送规则（固定档位，后续接 promotion_rules 表）：
  ≥ 3000分 → 赠 500分
  ≥ 2000分 → 赠 300分
  ≥ 1000分 → 赠 150分
  ≥ 500分  → 赠 50分
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from fastapi import Depends

router = APIRouter(prefix="/api/v1", tags=["stored-value"])

# ── 充值赠送固定档位（分） ──────────────────────────────────────────────
_BONUS_TIERS: list[tuple[int, int]] = [
    (300_000, 50_000),
    (200_000, 30_000),
    (100_000, 15_000),
    (50_000,   5_000),
]


def _calc_bonus(amount_fen: int) -> int:
    """根据充值金额计算赠送金额（分）"""
    for threshold, bonus in _BONUS_TIERS:
        if amount_fen >= threshold:
            return bonus
    return 0


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: dict) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, status: int = 400) -> HTTPException:
    return HTTPException(status_code=status, detail=msg)


# ── Pydantic 模型 ──────────────────────────────────────────────────────

class RechargeReq(BaseModel):
    amount_fen: int
    payment_method: str
    operator_id: str
    note: Optional[str] = None
    external_payment_id: Optional[str] = None

    @field_validator("amount_fen")
    @classmethod
    def validate_amount(cls, v: int) -> int:
        if v < 100:
            raise ValueError("充值金额最小100分（1元）")
        return v

    @field_validator("payment_method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        if v not in {"cash", "wechat", "alipay", "card"}:
            raise ValueError("payment_method must be cash/wechat/alipay/card")
        return v


class ConsumeReq(BaseModel):
    amount_fen: int
    order_id: str
    operator_id: str

    @field_validator("amount_fen")
    @classmethod
    def validate_amount(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("消费金额必须大于0")
        return v


class RefundReq(BaseModel):
    transaction_id: str
    amount_fen: int
    reason: str
    operator_id: str

    @field_validator("amount_fen")
    @classmethod
    def validate_amount(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("退款金额必须大于0")
        return v


# ── 工具函数 ───────────────────────────────────────────────────────────

async def _get_or_create_account(
    db: AsyncSession,
    tenant_id: str,
    member_id: str,
) -> dict:
    """查找或创建储值账户，返回账户行 dict"""
    row = await db.execute(
        text("""
            SELECT id, balance_fen, frozen_fen, total_recharged_fen, total_consumed_fen
            FROM stored_value_accounts
            WHERE tenant_id = :tid AND member_id = :mid AND is_deleted = FALSE
            LIMIT 1
        """),
        {"tid": tenant_id, "mid": member_id},
    )
    rec = row.mappings().first()
    if rec:
        return dict(rec)

    # 创建新账户
    new_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO stored_value_accounts
                (id, tenant_id, member_id, balance_fen, frozen_fen,
                 total_recharged_fen, total_consumed_fen)
            VALUES (:id, :tid, :mid, 0, 0, 0, 0)
        """),
        {"id": new_id, "tid": tenant_id, "mid": member_id},
    )
    return {
        "id": new_id,
        "balance_fen": 0,
        "frozen_fen": 0,
        "total_recharged_fen": 0,
        "total_consumed_fen": 0,
    }


async def _write_transaction(
    db: AsyncSession,
    *,
    tenant_id: str,
    account_id: str,
    member_id: str,
    txn_type: str,
    amount_fen: int,
    balance_before: int,
    balance_after: int,
    order_id: Optional[str] = None,
    operator_id: Optional[str] = None,
    note: Optional[str] = None,
    payment_method: Optional[str] = None,
    external_payment_id: Optional[str] = None,
) -> str:
    txn_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO stored_value_transactions
                (id, tenant_id, account_id, member_id, order_id,
                 type, amount_fen, balance_before_fen, balance_after_fen,
                 operator_id, note, payment_method, external_payment_id)
            VALUES
                (:id, :tid, :aid, :mid, :oid,
                 :tp, :amt, :bbf, :baf,
                 :opid, :note, :pm, :epid)
        """),
        {
            "id": txn_id,
            "tid": tenant_id,
            "aid": account_id,
            "mid": member_id,
            "oid": order_id,
            "tp": txn_type,
            "amt": amount_fen,
            "bbf": balance_before,
            "baf": balance_after,
            "opid": operator_id,
            "note": note,
            "pm": payment_method,
            "epid": external_payment_id,
        },
    )
    return txn_id


# ── GET 余额 + 最近20条流水 ────────────────────────────────────────────

@router.get("/members/{member_id}/stored-value")
async def get_stored_value(
    member_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id = _get_tenant_id(request)
    await db.execute(
        text("SET LOCAL app.tenant_id = :tid"), {"tid": tenant_id}
    )

    account = await _get_or_create_account(db, tenant_id, member_id)
    await db.commit()

    txn_rows = await db.execute(
        text("""
            SELECT id, type, amount_fen, balance_before_fen, balance_after_fen,
                   operator_id, note, payment_method, order_id, created_at
            FROM stored_value_transactions
            WHERE tenant_id = :tid AND member_id = :mid
            ORDER BY created_at DESC
            LIMIT 20
        """),
        {"tid": tenant_id, "mid": member_id},
    )
    transactions = [dict(r) for r in txn_rows.mappings()]
    # convert datetime to isoformat for JSON serialisation
    for t in transactions:
        if isinstance(t.get("created_at"), datetime):
            t["created_at"] = t["created_at"].isoformat()

    return _ok({
        "account_id": str(account["id"]),
        "member_id": member_id,
        "balance_fen": account["balance_fen"],
        "frozen_fen": account["frozen_fen"],
        "total_recharged_fen": account["total_recharged_fen"],
        "total_consumed_fen": account["total_consumed_fen"],
        "transactions": transactions,
    })


# ── POST 充值 ──────────────────────────────────────────────────────────

@router.post("/members/{member_id}/stored-value/recharge")
async def recharge(
    member_id: str,
    body: RechargeReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id = _get_tenant_id(request)
    await db.execute(
        text("SET LOCAL app.tenant_id = :tid"), {"tid": tenant_id}
    )

    account = await _get_or_create_account(db, tenant_id, member_id)
    account_id = str(account["id"])
    balance_before = account["balance_fen"]

    bonus_fen = _calc_bonus(body.amount_fen)
    total_credit = body.amount_fen + bonus_fen
    balance_after = balance_before + total_credit

    # 更新账户余额
    await db.execute(
        text("""
            UPDATE stored_value_accounts SET
                balance_fen         = balance_fen + :total,
                total_recharged_fen = total_recharged_fen + :total,
                updated_at          = NOW()
            WHERE id = :aid
        """),
        {"total": total_credit, "aid": account_id},
    )

    # 写主充值流水
    note_text = body.note or ""
    if bonus_fen > 0:
        note_text = f"充{body.amount_fen}分赠{bonus_fen}分" + (f" | {body.note}" if body.note else "")

    txn_id = await _write_transaction(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        member_id=member_id,
        txn_type="recharge",
        amount_fen=total_credit,
        balance_before=balance_before,
        balance_after=balance_after,
        operator_id=body.operator_id,
        note=note_text,
        payment_method=body.payment_method,
        external_payment_id=body.external_payment_id,
    )

    await db.commit()

    return _ok({
        "transaction_id": txn_id,
        "amount_fen": body.amount_fen,
        "bonus_fen": bonus_fen,
        "total_credited_fen": total_credit,
        "balance_after_fen": balance_after,
    })


# ── POST 消费扣款 ──────────────────────────────────────────────────────

@router.post("/members/{member_id}/stored-value/consume")
async def consume(
    member_id: str,
    body: ConsumeReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id = _get_tenant_id(request)
    await db.execute(
        text("SET LOCAL app.tenant_id = :tid"), {"tid": tenant_id}
    )

    account = await _get_or_create_account(db, tenant_id, member_id)
    account_id = str(account["id"])
    balance_before = account["balance_fen"]
    available = balance_before - account["frozen_fen"]

    if available < body.amount_fen:
        insufficient = body.amount_fen - available
        return _ok({
            "success": False,
            "balance_after_fen": balance_before,
            "insufficient_fen": insufficient,
        })

    balance_after = balance_before - body.amount_fen

    await db.execute(
        text("""
            UPDATE stored_value_accounts SET
                balance_fen        = balance_fen - :amt,
                total_consumed_fen = total_consumed_fen + :amt,
                updated_at         = NOW()
            WHERE id = :aid
        """),
        {"amt": body.amount_fen, "aid": account_id},
    )

    txn_id = await _write_transaction(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        member_id=member_id,
        txn_type="consume",
        amount_fen=-body.amount_fen,
        balance_before=balance_before,
        balance_after=balance_after,
        order_id=body.order_id,
        operator_id=body.operator_id,
        note=f"订单消费",
    )

    await db.commit()

    return _ok({
        "success": True,
        "transaction_id": txn_id,
        "balance_after_fen": balance_after,
        "insufficient_fen": 0,
    })


# ── POST 退款回储值 ────────────────────────────────────────────────────

@router.post("/members/{member_id}/stored-value/refund")
async def refund(
    member_id: str,
    body: RefundReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id = _get_tenant_id(request)
    await db.execute(
        text("SET LOCAL app.tenant_id = :tid"), {"tid": tenant_id}
    )

    # 校验原始消费流水
    orig_row = await db.execute(
        text("""
            SELECT id, account_id, amount_fen, type
            FROM stored_value_transactions
            WHERE id = :txn_id AND tenant_id = :tid
        """),
        {"txn_id": body.transaction_id, "tid": tenant_id},
    )
    orig = orig_row.mappings().first()
    if not orig:
        raise _err("原始交易记录不存在", 404)
    if orig["type"] not in ("consume",):
        raise _err("只能对消费流水发起退款")
    if body.amount_fen > abs(orig["amount_fen"]):
        raise _err("退款金额不可超过原消费金额")

    account_id = str(orig["account_id"])

    acc_row = await db.execute(
        text("SELECT balance_fen FROM stored_value_accounts WHERE id = :aid"),
        {"aid": account_id},
    )
    acc = acc_row.mappings().first()
    if not acc:
        raise _err("账户不存在", 404)

    balance_before = acc["balance_fen"]
    balance_after = balance_before + body.amount_fen

    await db.execute(
        text("""
            UPDATE stored_value_accounts SET
                balance_fen        = balance_fen + :amt,
                total_consumed_fen = GREATEST(total_consumed_fen - :amt, 0),
                updated_at         = NOW()
            WHERE id = :aid
        """),
        {"amt": body.amount_fen, "aid": account_id},
    )

    txn_id = await _write_transaction(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        member_id=member_id,
        txn_type="refund",
        amount_fen=body.amount_fen,
        balance_before=balance_before,
        balance_after=balance_after,
        operator_id=body.operator_id,
        note=body.reason,
    )

    await db.commit()

    return _ok({
        "transaction_id": txn_id,
        "refunded_fen": body.amount_fen,
        "balance_after_fen": balance_after,
    })
