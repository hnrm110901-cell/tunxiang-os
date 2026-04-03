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
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/orders", tags=["split-payment"])


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

    # TODO: 从 DB 查询订单，带 tenant_id 过滤
    # async with get_db_with_tenant(tenant_id) as db:
    #     order = await db.execute(
    #         select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id)
    #     )
    #     order = order.scalar_one_or_none()
    # if not order:
    #     raise HTTPException(status_code=404, detail="订单不存在")
    # if order.status != "open":
    #     raise HTTPException(status_code=409, detail=f"订单状态为 {order.status}，无法发起分摊")

    # TODO: 检查是否已存在分摊记录（防重复初始化）
    # existing = await db.execute(
    #     select(SplitPayment).where(
    #         SplitPayment.order_id == order_id,
    #         SplitPayment.tenant_id == tenant_id,
    #         SplitPayment.is_deleted.is_(False),
    #     )
    # )
    # if existing.scalars().first():
    #     raise HTTPException(status_code=409, detail="该订单已初始化分摊，请勿重复操作")

    # TODO: 获取订单总金额（分）
    # total_fen = order.total_fen
    total_fen = 0  # placeholder，实际从订单取

    amounts = _calc_split_amounts(total_fen, req.total_splits)

    # TODO: 批量写入 split_payments 表
    # records = [
    #     SplitPayment(
    #         tenant_id=tenant_id,
    #         order_id=order_id,
    #         split_no=i + 1,
    #         total_splits=req.total_splits,
    #         amount_fen=amt,
    #         payment_method="pending",  # 初始化时不指定支付方式
    #         status="pending",
    #         created_by=request.state.employee_id,
    #     )
    #     for i, amt in enumerate(amounts)
    # ]
    # db.add_all(records)
    # await db.commit()

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
) -> dict:
    """
    返回该订单的分摊列表及每份状态（pending/paid/cancelled）。
    """
    tenant_id = _get_tenant_id(request)

    # TODO: 从 DB 查询分摊记录，带 tenant_id 过滤
    # async with get_db_with_tenant(tenant_id) as db:
    #     result = await db.execute(
    #         select(SplitPayment)
    #         .where(
    #             SplitPayment.order_id == order_id,
    #             SplitPayment.tenant_id == tenant_id,
    #             SplitPayment.is_deleted.is_(False),
    #         )
    #         .order_by(SplitPayment.split_no)
    #     )
    #     splits = result.scalars().all()
    # if not splits:
    #     raise HTTPException(status_code=404, detail="该订单无分摊记录")

    # TODO: 替换为真实 DB 数据
    splits: list[dict] = []  # placeholder

    paid_count = sum(1 for s in splits if s.get("status") == "paid")
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

    # TODO: 查询目标 split_payment 记录
    # async with get_db_with_tenant(tenant_id) as db:
    #     result = await db.execute(
    #         select(SplitPayment).where(
    #             SplitPayment.order_id == order_id,
    #             SplitPayment.tenant_id == tenant_id,
    #             SplitPayment.split_no == split_no,
    #             SplitPayment.is_deleted.is_(False),
    #         )
    #     )
    #     split = result.scalar_one_or_none()
    # if not split:
    #     raise HTTPException(status_code=404, detail=f"第 {split_no} 份分摊记录不存在")
    # if split.status == "paid":
    #     raise HTTPException(status_code=409, detail=f"第 {split_no} 份已结账")
    # if split.status == "cancelled":
    #     raise HTTPException(status_code=409, detail=f"第 {split_no} 份已取消")

    now = datetime.now(timezone.utc)

    # TODO: 更新 split_payment 状态
    # split.status = "paid"
    # split.payment_method = req.payment_method
    # split.member_id = req.member_id
    # split.paid_at = now
    # split.updated_at = now
    # await db.flush()

    # TODO: 检查是否全部已付，若是则关闭订单
    # all_splits = await db.execute(
    #     select(SplitPayment).where(
    #         SplitPayment.order_id == order_id,
    #         SplitPayment.tenant_id == tenant_id,
    #         SplitPayment.is_deleted.is_(False),
    #     )
    # )
    # all_splits = all_splits.scalars().all()
    # all_paid = all(s.status == "paid" for s in all_splits)
    # if all_paid:
    #     order = await db.get(Order, order_id)
    #     if order:
    #         order.status = "paid"
    #         order.updated_at = now
    # await db.commit()

    all_paid = False  # placeholder

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
