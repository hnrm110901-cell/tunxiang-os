"""顾客自助分账 / 预授权结账路由

POST /api/v1/orders/{order_id}/self-pay-link  — 生成自助付款 token（JWT, 15分钟）
GET  /api/v1/orders/{order_id}/payment-status — 查询支付状态
POST /api/v1/pay/self/{token}                 — 顾客端提交支付（验证 token，更新订单）
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["self-pay"])

_SECRET_KEY = os.getenv("SELF_PAY_JWT_SECRET", "txos-self-pay-secret-change-in-prod")
_ALGORITHM = "HS256"
_TOKEN_TTL_MINUTES = 15


# ──────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────

def _ok(data: dict) -> dict:
    return {"ok": True, "data": data, "error": None}


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _create_token(order_id: str, amount_fen: int, tenant_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=_TOKEN_TTL_MINUTES)
    payload = {
        "sub": order_id,
        "amount_fen": amount_fen,
        "tenant_id": tenant_id,
        "exp": expire,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, _SECRET_KEY, algorithm=_ALGORITHM)


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, _SECRET_KEY, algorithms=[_ALGORITHM])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail={"ok": False, "error": {"message": f"无效或已过期的付款链接: {exc}"}}) from exc


# ──────────────────────────────────────────────
#  请求模型
# ──────────────────────────────────────────────

class SelfPayLinkReq(BaseModel):
    split_count: Optional[int] = None  # None = 全单; >=2 = 按人分摊


class GuestPayReq(BaseModel):
    payment_method: str = "wechat"  # wechat | alipay
    payer_name: Optional[str] = None


# ──────────────────────────────────────────────
#  1. 生成自助付款 token
# ──────────────────────────────────────────────

@router.post("/orders/{order_id}/self-pay-link")
async def create_self_pay_link(
    order_id: str,
    req: SelfPayLinkReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """生成顾客自助付款 token（JWT, 15 分钟有效）"""
    tenant_id = _get_tenant_id(request)

    row = await db.execute(
        text(
            "SELECT id, status, final_amount_fen, total_amount_fen, table_no "
            "FROM orders "
            "WHERE id = :oid AND tenant_id = :tid"
        ),
        {"oid": order_id, "tid": tenant_id},
    )
    order = row.mappings().first()

    if not order:
        raise HTTPException(status_code=404, detail={"ok": False, "error": {"message": "订单不存在"}})
    if order["status"] == "paid":
        raise HTTPException(status_code=409, detail={"ok": False, "error": {"message": "订单已结账"}})

    total_fen: int = order["final_amount_fen"] or order["total_amount_fen"] or 0
    split_count = req.split_count or 1
    if split_count < 1:
        raise HTTPException(status_code=422, detail={"ok": False, "error": {"message": "split_count 必须 >= 1"}})

    per_person_fen = total_fen // split_count

    token = _create_token(order_id, per_person_fen, tenant_id)
    amount_yuan = per_person_fen / 100

    log.info("self_pay_link_created", order_id=order_id, split_count=split_count, amount_fen=per_person_fen)

    return _ok({
        "order_id": order_id,
        "token": token,
        "total_amount_fen": total_fen,
        "per_person_amount_fen": per_person_fen,
        "split_count": split_count,
        "deep_link": f"txos://pay/{order_id}?amount={amount_yuan:.2f}&token={token}",
        "expires_in_seconds": _TOKEN_TTL_MINUTES * 60,
    })


# ──────────────────────────────────────────────
#  2. 查询支付状态
# ──────────────────────────────────────────────

@router.get("/orders/{order_id}/payment-status")
async def get_payment_status(
    order_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """轮询订单支付状态"""
    tenant_id = _get_tenant_id(request)

    row = await db.execute(
        text(
            "SELECT id, status, final_amount_fen, total_amount_fen, completed_at "
            "FROM orders "
            "WHERE id = :oid AND tenant_id = :tid"
        ),
        {"oid": order_id, "tid": tenant_id},
    )
    order = row.mappings().first()

    if not order:
        raise HTTPException(status_code=404, detail={"ok": False, "error": {"message": "订单不存在"}})

    paid = order["status"] == "paid"
    return _ok({
        "order_id": order_id,
        "status": order["status"],
        "paid": paid,
        "amount_fen": order["final_amount_fen"] or order["total_amount_fen"] or 0,
        "completed_at": order["completed_at"].isoformat() if paid and order["completed_at"] else None,
    })


# ──────────────────────────────────────────────
#  3. 顾客端提交支付
# ──────────────────────────────────────────────

@router.post("/pay/self/{token}")
async def guest_submit_payment(
    token: str,
    req: GuestPayReq,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """顾客扫码后提交支付。验证 JWT token，更新订单状态为 paid。"""
    claims = _decode_token(token)
    order_id: str = claims["sub"]
    amount_fen: int = claims["amount_fen"]
    tenant_id: str = claims["tenant_id"]

    now = datetime.now(timezone.utc)

    row = await db.execute(
        text(
            "SELECT id, status FROM orders "
            "WHERE id = :oid AND tenant_id = :tid "
            "FOR UPDATE"
        ),
        {"oid": order_id, "tid": tenant_id},
    )
    order = row.mappings().first()

    if not order:
        raise HTTPException(status_code=404, detail={"ok": False, "error": {"message": "订单不存在"}})
    if order["status"] == "paid":
        return _ok({"order_id": order_id, "status": "already_paid", "paid_at": None})

    await db.execute(
        text(
            "UPDATE orders "
            "SET status = 'paid', completed_at = :now, updated_at = :now "
            "WHERE id = :oid AND tenant_id = :tid"
        ),
        {"now": now, "oid": order_id, "tid": tenant_id},
    )

    payment_no = f"SPL-{uuid.uuid4().hex[:16].upper()}"
    await db.execute(
        text(
            "INSERT INTO payments "
            "(id, tenant_id, order_id, payment_no, method, amount_fen, status, "
            " is_actual_revenue, actual_revenue_ratio, payment_category, "
            " notes, paid_at, created_at, updated_at, is_deleted) "
            "VALUES "
            "(:id, :tid, :oid, :pno, :method, :amount, 'paid', "
            " true, 1.0, '移动支付', "
            " :notes, :paid_at, :now, :now, false)"
        ),
        {
            "id": str(uuid.uuid4()),
            "tid": tenant_id,
            "oid": order_id,
            "pno": payment_no,
            "method": req.payment_method,
            "amount": amount_fen,
            "notes": f"顾客自助付款 payer={req.payer_name or '匿名'}",
            "paid_at": now,
            "now": now,
        },
    )

    await db.commit()

    log.info("guest_self_pay_success", order_id=order_id, amount_fen=amount_fen, method=req.payment_method)

    return _ok({
        "order_id": order_id,
        "status": "paid",
        "paid_at": now.isoformat(),
        "payment_no": payment_no,
        "amount_fen": amount_fen,
    })
