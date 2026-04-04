"""分摊结账 API

路由前缀：/api/v1/orders

端点：
  POST /api/v1/orders/{order_id}/split-pay/init             — 初始化分摊（设定总份数）
  GET  /api/v1/orders/{order_id}/split-pay                  — 获取分摊状态列表
  POST /api/v1/orders/{order_id}/split-pay/{split_no}/settle — 某份结账
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/orders", tags=["split-payment"])

_SET_TENANT_SQL = text("SELECT set_config('app.tenant_id', :tid, true)")


# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def _ok(data: object) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: str = "BAD_REQUEST") -> dict:
    return {"ok": False, "data": None, "error": {"code": code, "message": msg}}


def _get_tenant_id(request: Request) -> str:
    tenant_id = (
        getattr(request.state, "tenant_id", None)
        or request.headers.get("X-Tenant-ID", "")
    )
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Missing X-Tenant-ID")
    return tenant_id


# ─── Pydantic 模型 ────────────────────────────────────────────────────────────

class InitSplitPayRequest(BaseModel):
    total_splits: int = Field(..., ge=2, le=10, description="总份数，2-10")

    @field_validator("total_splits")
    @classmethod
    def validate_splits(cls, v: int) -> int:
        if v < 2 or v > 10:
            raise ValueError("total_splits 必须在 2-10 之间")
        return v


class SplitSettleRequest(BaseModel):
    payment_method: str = Field(
        ..., description="支付方式：wechat|alipay|cash|credit|tab"
    )
    member_id: Optional[str] = Field(None, description="关联会员 ID（可选）")

    @field_validator("payment_method")
    @classmethod
    def validate_payment_method(cls, v: str) -> str:
        allowed = {"wechat", "alipay", "cash", "credit", "tab"}
        if v not in allowed:
            raise ValueError(f"payment_method 必须是 {allowed} 之一")
        return v


# ─── 均等分摊金额计算 ─────────────────────────────────────────────────────────

def _calc_split_amounts(total_fen: int, splits: int) -> list[int]:
    """
    均等分摊，尾差加到最后一份。
    例：total=100, splits=3 → [33, 33, 34]
    """
    each = total_fen // splits
    remainder = total_fen - each * splits
    amounts = [each] * splits
    amounts[-1] += remainder  # 尾差加到最后一份
    return amounts


# ─── 端点 ─────────────────────────────────────────────────────────────────────

@router.post("/{order_id}/split-pay/init", summary="初始化分摊结账")
async def init_split_pay(
    order_id: str,
    req: InitSplitPayRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    初始化分摊：按 total_splits 均等分摊订单金额，批量生成 split_payments 记录。

    业务流程：
      1. 验证 order 存在且状态为 open（未结账）
      2. 计算每份金额（均等分，尾差加到最后一份）
      3. 批量写入 split_payments 表（status=pending）
      4. 返回各份金额明细
    """
    tenant_id = _get_tenant_id(request)
    await db.execute(_SET_TENANT_SQL, {"tid": tenant_id})

    # 1. 查询订单，验证状态
    order_row = (
        await db.execute(
            text(
                "SELECT id, status, total_amount_fen "
                "FROM orders "
                "WHERE id = :oid AND tenant_id = :tid AND is_deleted = FALSE"
            ),
            {"oid": order_id, "tid": tenant_id},
        )
    ).mappings().first()

    if not order_row:
        raise HTTPException(status_code=404, detail="订单不存在")

    allowed_statuses = ("pending", "confirmed", "preparing", "ready", "served")
    if order_row["status"] not in allowed_statuses:
        raise HTTPException(
            status_code=409,
            detail=f"订单状态为 {order_row['status']}，无法发起分摊",
        )

    # 2. 检查是否已存在分摊记录（防重复初始化）
    existing = (
        await db.execute(
            text(
                "SELECT id FROM split_payments "
                "WHERE order_id = :oid AND tenant_id = :tid AND is_deleted = FALSE "
                "LIMIT 1"
            ),
            {"oid": order_id, "tid": tenant_id},
        )
    ).first()

    if existing:
        raise HTTPException(status_code=409, detail="该订单已初始化分摊，请勿重复操作")

    # 3. 计算分摊金额
    total_fen: int = order_row["total_amount_fen"]
    amounts = _calc_split_amounts(total_fen, req.total_splits)

    # 4. 批量写入 split_payments 表
    created_by = getattr(request.state, "employee_id", None)
    for i, amt in enumerate(amounts):
        await db.execute(
            text(
                "INSERT INTO split_payments "
                "(id, tenant_id, order_id, split_no, total_splits, amount_fen, "
                " payment_method, status, created_by) "
                "VALUES (:id, :tid, :oid, :sno, :ts, :amt, :pm, 'pending', :cb)"
            ),
            {
                "id": str(uuid.uuid4()),
                "tid": tenant_id,
                "oid": order_id,
                "sno": i + 1,
                "ts": req.total_splits,
                "amt": amt,
                "pm": "cash",  # 默认值，结账时更新为实际支付方式
                "cb": created_by,
            },
        )
    await db.flush()

    splits_detail = [
        {
            "split_no": i + 1,
            "total_splits": req.total_splits,
            "amount_fen": amt,
            "amount_yuan": round(amt / 100, 2),
            "status": "pending",
        }
        for i, amt in enumerate(amounts)
    ]

    logger.info(
        "split_pay.init",
        order_id=order_id,
        tenant_id=tenant_id,
        total_splits=req.total_splits,
        total_fen=total_fen,
    )
    return _ok(
        {
            "order_id": order_id,
            "total_splits": req.total_splits,
            "total_fen": total_fen,
            "splits": splits_detail,
        }
    )


@router.get("/{order_id}/split-pay", summary="获取分摊状态")
async def get_split_pay_status(
    order_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    返回该订单的分摊列表及每份状态（pending/paid/cancelled）。
    """
    tenant_id = _get_tenant_id(request)
    await db.execute(_SET_TENANT_SQL, {"tid": tenant_id})

    result = await db.execute(
        text(
            "SELECT split_no, total_splits, amount_fen, payment_method, "
            "       member_id, status, paid_at "
            "FROM split_payments "
            "WHERE order_id = :oid AND tenant_id = :tid AND is_deleted = FALSE "
            "ORDER BY split_no"
        ),
        {"oid": order_id, "tid": tenant_id},
    )
    rows = result.mappings().all()

    if not rows:
        raise HTTPException(status_code=404, detail="该订单无分摊记录")

    splits = [
        {
            "split_no": r["split_no"],
            "total_splits": r["total_splits"],
            "amount_fen": r["amount_fen"],
            "amount_yuan": round(r["amount_fen"] / 100, 2),
            "payment_method": r["payment_method"],
            "member_id": str(r["member_id"]) if r["member_id"] else None,
            "status": r["status"],
            "paid_at": r["paid_at"].isoformat() if r["paid_at"] else None,
        }
        for r in rows
    ]

    paid_count = sum(1 for s in splits if s["status"] == "paid")
    total_splits = len(splits)
    all_paid = total_splits > 0 and paid_count == total_splits

    return _ok(
        {
            "order_id": order_id,
            "total_splits": total_splits,
            "paid_count": paid_count,
            "all_paid": all_paid,
            "splits": splits,
        }
    )


@router.post("/{order_id}/split-pay/{split_no}/settle", summary="某份结账")
async def settle_split(
    order_id: str,
    split_no: int,
    req: SplitSettleRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    对第 split_no 份执行结账：
      1. 更新对应 split_payment 记录 status='paid'，记录支付方式和 paid_at
      2. 检查该订单所有份是否全部已付 → 若是，更新 order.status='completed'
      3. 返回结果
    """
    tenant_id = _get_tenant_id(request)
    await db.execute(_SET_TENANT_SQL, {"tid": tenant_id})

    if split_no < 1:
        raise HTTPException(status_code=400, detail="split_no 必须 >= 1")

    # 1. 查询目标 split_payment 记录
    split_row = (
        await db.execute(
            text(
                "SELECT id, status FROM split_payments "
                "WHERE order_id = :oid AND tenant_id = :tid "
                "  AND split_no = :sno AND is_deleted = FALSE"
            ),
            {"oid": order_id, "tid": tenant_id, "sno": split_no},
        )
    ).mappings().first()

    if not split_row:
        raise HTTPException(
            status_code=404, detail=f"第 {split_no} 份分摊记录不存在"
        )
    if split_row["status"] == "paid":
        raise HTTPException(
            status_code=409, detail=f"第 {split_no} 份已结账"
        )
    if split_row["status"] == "cancelled":
        raise HTTPException(
            status_code=409, detail=f"第 {split_no} 份已取消"
        )

    now = datetime.now(timezone.utc)

    # 2. 更新 split_payment 状态
    await db.execute(
        text(
            "UPDATE split_payments "
            "SET status = 'paid', "
            "    payment_method = :pm, "
            "    member_id = :mid, "
            "    paid_at = :now, "
            "    updated_at = :now "
            "WHERE id = :sid AND tenant_id = :tid"
        ),
        {
            "pm": req.payment_method,
            "mid": req.member_id,
            "now": now,
            "sid": str(split_row["id"]),
            "tid": tenant_id,
        },
    )

    # 3. 检查是否全部已付
    unpaid_count_row = (
        await db.execute(
            text(
                "SELECT COUNT(*) AS cnt FROM split_payments "
                "WHERE order_id = :oid AND tenant_id = :tid "
                "  AND is_deleted = FALSE AND status != 'paid'"
            ),
            {"oid": order_id, "tid": tenant_id},
        )
    ).mappings().first()

    all_paid = unpaid_count_row is not None and unpaid_count_row["cnt"] == 0

    # 4. 若全部已付，更新订单状态为 completed
    if all_paid:
        await db.execute(
            text(
                "UPDATE orders "
                "SET status = 'completed', "
                "    completed_at = :now, "
                "    updated_at = :now "
                "WHERE id = :oid AND tenant_id = :tid AND is_deleted = FALSE"
            ),
            {"now": now, "oid": order_id, "tid": tenant_id},
        )

    await db.flush()

    logger.info(
        "split_pay.settle",
        order_id=order_id,
        tenant_id=tenant_id,
        split_no=split_no,
        payment_method=req.payment_method,
        member_id=req.member_id,
        all_paid=all_paid,
    )
    return _ok(
        {
            "order_id": order_id,
            "split_no": split_no,
            "status": "paid",
            "payment_method": req.payment_method,
            "member_id": req.member_id,
            "paid_at": now.isoformat(),
            "order_closed": all_paid,
        }
    )
