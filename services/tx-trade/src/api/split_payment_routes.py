"""分摊结账 API

路由前缀：/api/v1/orders

端点：
  POST /api/v1/orders/{order_id}/split-pay/init             — 初始化分摊（设定总份数）
  GET  /api/v1/orders/{order_id}/split-pay                  — 获取分摊状态列表
  POST /api/v1/orders/{order_id}/split-pay/{split_no}/settle — 某份结账
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/orders", tags=["split-payment"])


# ─── 工具函数 ─────────────────────────────────────────────────────────────────


def _ok(data: object) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: str = "BAD_REQUEST") -> dict:
    return {"ok": False, "data": None, "error": {"code": code, "message": msg}}


def _get_tenant_id(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Missing X-Tenant-ID")
    return tenant_id


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


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
    payment_method: str = Field(..., description="支付方式：wechat|alipay|cash|credit|tab")
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

    try:
        await _set_tenant(db, tenant_id)

        # 查询订单，获取 final_amount_fen
        order_row = await db.execute(
            text("SELECT final_amount_fen FROM orders WHERE id = :oid AND is_deleted = FALSE"),
            {"oid": order_id},
        )
        order = order_row.fetchone()
        if not order:
            raise HTTPException(status_code=404, detail="订单不存在")

        total_fen: int = order.final_amount_fen

        # 检查是否已存在进行中的分摊记录（防重复初始化）
        existing_row = await db.execute(
            text("SELECT status FROM order_split_payments WHERE order_id = :oid AND is_deleted = FALSE"),
            {"oid": order_id},
        )
        existing = existing_row.fetchall()
        if existing and any(r.status != "cancelled" for r in existing):
            raise HTTPException(status_code=400, detail="已存在进行中的分摊")

        amounts = _calc_split_amounts(total_fen, req.total_splits)

        # 批量 INSERT 分摊记录
        insert_rows = []
        for i, amt in enumerate(amounts):
            result = await db.execute(
                text(
                    "INSERT INTO order_split_payments "
                    "(order_id, split_no, amount_fen, payer_name, status, tenant_id, created_at, is_deleted) "
                    "VALUES (:order_id, :split_no, :amount_fen, :payer_name, 'pending', :tenant_id, NOW(), FALSE) "
                    "RETURNING id, split_no, amount_fen, status"
                ),
                {
                    "order_id": order_id,
                    "split_no": i + 1,
                    "amount_fen": amt,
                    "payer_name": "",
                    "tenant_id": tenant_id,
                },
            )
            row = result.fetchone()
            insert_rows.append(row)

        await db.commit()

        splits_detail = [
            {
                "split_no": row.split_no,
                "total_splits": req.total_splits,
                "amount_fen": row.amount_fen,
                "amount_yuan": round(row.amount_fen / 100, 2),
                "status": row.status,
            }
            for row in insert_rows
        ]

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("split_pay.init.db_error", order_id=order_id, error=str(exc))
        raise HTTPException(status_code=500, detail="数据库错误") from exc

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

    try:
        await _set_tenant(db, tenant_id)

        result = await db.execute(
            text(
                "SELECT id, split_no, amount_fen, payer_name, status, tenant_id, created_at "
                "FROM order_split_payments "
                "WHERE order_id = :oid AND is_deleted = FALSE "
                "ORDER BY split_no"
            ),
            {"oid": order_id},
        )
        rows = result.fetchall()

    except SQLAlchemyError as exc:
        logger.error("split_pay.list.db_error", order_id=order_id, error=str(exc))
        raise HTTPException(status_code=500, detail="数据库错误") from exc

    if not rows:
        return _ok(
            {
                "order_id": order_id,
                "total_splits": 0,
                "paid_count": 0,
                "all_paid": False,
                "splits": [],
            }
        )

    splits = [
        {
            "id": str(row.id),
            "split_no": row.split_no,
            "amount_fen": row.amount_fen,
            "amount_yuan": round(row.amount_fen / 100, 2),
            "payer_name": row.payer_name,
            "status": row.status,
        }
        for row in rows
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
      2. 检查该订单所有份是否全部已付 → 若是，更新 order.status='paid'
      3. 返回结果
    """
    tenant_id = _get_tenant_id(request)

    if split_no < 1:
        raise HTTPException(status_code=400, detail="split_no 必须 >= 1")

    now = datetime.now(timezone.utc)

    try:
        await _set_tenant(db, tenant_id)

        # UPDATE 目标分摊记录，RETURNING id 验证是否命中
        update_result = await db.execute(
            text(
                "UPDATE order_split_payments "
                "SET status = 'paid', paid_at = NOW() "
                "WHERE order_id = :oid AND split_no = :sno AND is_deleted = FALSE "
                "RETURNING id"
            ),
            {"oid": order_id, "sno": split_no},
        )
        updated = update_result.fetchone()
        if not updated:
            raise HTTPException(status_code=404, detail=f"第 {split_no} 份分摊记录不存在")

        # 查询是否还有未付的分摊项
        unpaid_result = await db.execute(
            text(
                "SELECT COUNT(*) AS cnt FROM order_split_payments "
                "WHERE order_id = :oid AND status != 'paid' AND is_deleted = FALSE"
            ),
            {"oid": order_id},
        )
        unpaid_row = unpaid_result.fetchone()
        all_paid: bool = unpaid_row.cnt == 0

        await db.commit()

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error(
            "split_pay.settle.db_error",
            order_id=order_id,
            split_no=split_no,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail="数据库错误") from exc

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
