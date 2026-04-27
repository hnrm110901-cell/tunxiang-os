"""支付核心 API 路由

端点：
  POST /api/v1/pay/create          — 发起支付
  POST /api/v1/pay/query           — 查询支付状态
  POST /api/v1/pay/refund          — 退款
  POST /api/v1/pay/close           — 关闭未支付交易
  POST /api/v1/pay/split           — 多方式拆单支付
  GET  /api/v1/pay/daily-summary   — 当日支付汇总
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from ..channels.base import PayMethod, TradeType

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/pay", tags=["支付中枢"])


# ─── 请求/响应模型 ─────────────────────────────────────────────────


class CreatePaymentReq(BaseModel):
    store_id: str
    order_id: str
    amount_fen: int = Field(..., gt=0, description="支付金额（分）")
    method: PayMethod
    trade_type: TradeType = TradeType.B2C
    auth_code: Optional[str] = None
    openid: Optional[str] = None
    description: str = ""
    idempotency_key: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class QueryPaymentReq(BaseModel):
    payment_id: str
    trade_no: Optional[str] = None


class RefundReq(BaseModel):
    payment_id: str
    refund_amount_fen: int = Field(..., gt=0)
    reason: str = ""
    refund_id: Optional[str] = None


class ClosePaymentReq(BaseModel):
    payment_id: str


class SplitPaymentEntry(BaseModel):
    method: PayMethod
    amount_fen: int = Field(..., gt=0)
    auth_code: Optional[str] = None
    openid: Optional[str] = None


class SplitPaymentReq(BaseModel):
    store_id: str
    order_id: str
    entries: list[SplitPaymentEntry] = Field(..., min_length=1)
    metadata: dict = Field(default_factory=dict)


class DailySummaryQuery(BaseModel):
    store_id: str
    summary_date: date = Field(default_factory=date.today)


# ─── 标准响应 ───────────────────────────────────────────────────────


def ok(data: dict | list | None = None) -> dict:
    return {"ok": True, "data": data or {}}


def err(code: str, message: str, status: int = 400) -> None:
    raise HTTPException(status_code=status, detail={"ok": False, "error": {"code": code, "message": message}})


# ─── 端点 ───────────────────────────────────────────────────────────


@router.post("/create")
async def create_payment(
    req: CreatePaymentReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """发起支付

    根据 (tenant_id, store_id, method) 路由到对应渠道，
    走 Saga 事务保证一致性。
    """
    from ..deps import get_payment_service

    svc = await get_payment_service()
    result = await svc.create_payment(
        tenant_id=x_tenant_id,
        store_id=req.store_id,
        order_id=req.order_id,
        amount_fen=req.amount_fen,
        method=req.method,
        trade_type=req.trade_type,
        auth_code=req.auth_code,
        openid=req.openid,
        description=req.description,
        idempotency_key=req.idempotency_key,
        metadata=req.metadata,
    )
    return ok(result.model_dump(mode="json"))


@router.post("/query")
async def query_payment(
    req: QueryPaymentReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """查询支付状态"""
    from ..deps import get_payment_service

    svc = await get_payment_service()
    result = await svc.query_payment(req.payment_id, req.trade_no)
    return ok(result.model_dump(mode="json"))


@router.post("/refund")
async def refund_payment(
    req: RefundReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """退款"""
    from ..deps import get_payment_service

    svc = await get_payment_service()
    result = await svc.refund(
        payment_id=req.payment_id,
        refund_amount_fen=req.refund_amount_fen,
        reason=req.reason,
        refund_id=req.refund_id,
    )
    return ok(result.model_dump(mode="json"))


@router.post("/close")
async def close_payment(
    req: ClosePaymentReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """关闭未支付交易"""
    from ..deps import get_payment_service

    svc = await get_payment_service()
    closed = await svc.close_payment(req.payment_id)
    return ok({"closed": closed})


@router.post("/split")
async def split_payment(
    req: SplitPaymentReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """多方式拆单支付"""
    from ..deps import get_payment_service
    from ..orchestrator.split_pay import SplitEntry

    svc = await get_payment_service()
    entries = [
        SplitEntry(method=e.method, amount_fen=e.amount_fen, auth_code=e.auth_code, openid=e.openid)
        for e in req.entries
    ]
    result = await svc.split_payment(
        tenant_id=x_tenant_id,
        store_id=req.store_id,
        order_id=req.order_id,
        entries=entries,
    )
    return ok(result.model_dump(mode="json"))


@router.get("/daily-summary")
async def daily_summary(
    store_id: str,
    summary_date: date = None,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """当日支付汇总（按方式分组）"""
    from ..deps import get_payment_service

    svc = await get_payment_service()
    data = await svc.daily_summary(
        tenant_id=x_tenant_id,
        store_id=store_id,
        summary_date=summary_date or date.today(),
    )
    return ok(data)
