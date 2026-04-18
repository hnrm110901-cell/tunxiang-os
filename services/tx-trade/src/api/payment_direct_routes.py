"""支付直连 API — 微信/支付宝/银联 + 退款 + 并发支付 + 风控

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。

Sprint A4：所有写操作均加 require_role 拦截 + write_audit 留痕。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..security.rbac import UserContext, require_role
from ..services.payment_direct import (
    create_alipay_payment,
    create_unionpay_payment,
    create_wechat_payment,
    get_payment_risk_check,
    handle_concurrent_payment,
    process_refund,
    query_payment_status,
)
from ..services.trade_audit_log import write_audit

router = APIRouter(prefix="/api/v1/payment-direct", tags=["payment-direct"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data) -> dict:
    return {"ok": True, "data": data, "error": None}


# ─── 请求模型 ───


class WechatPayReq(BaseModel):
    order_id: str
    amount_fen: int = Field(..., gt=0)
    openid: Optional[str] = None
    trade_type: str = "JSAPI"
    description: str = ""


class AlipayPayReq(BaseModel):
    order_id: str
    amount_fen: int = Field(..., gt=0)
    buyer_id: Optional[str] = None
    subject: str = ""


class UnionpayPayReq(BaseModel):
    order_id: str
    amount_fen: int = Field(..., gt=0)
    card_no_masked: Optional[str] = None


class RefundReq(BaseModel):
    payment_id: str
    amount_fen: int = Field(..., gt=0)
    reason: str = ""


class ConcurrentPayReq(BaseModel):
    order_id: str
    payments: list[dict] = Field(..., min_length=1, description="[{channel, amount_fen}]")


class RiskCheckReq(BaseModel):
    order_id: str
    amount_fen: int = Field(default=0, ge=0)
    payment_count_today: int = Field(default=0, ge=0)


# ─── 路由 ───


@router.post("/wechat")
async def api_wechat_pay(
    body: WechatPayReq,
    request: Request,
    user: UserContext = Depends(require_role("cashier", "store_manager", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """微信支付下单"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await create_wechat_payment(
            order_id=body.order_id,
            amount_fen=body.amount_fen,
            tenant_id=tenant_id,
            openid=body.openid,
            trade_type=body.trade_type,
            description=body.description,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await write_audit(
        db,
        tenant_id=tenant_id,
        store_id=user.store_id,
        user_id=user.user_id,
        user_role=user.role,
        action="payment.wechat.create",
        target_type="order",
        target_id=body.order_id,
        amount_fen=body.amount_fen,
        client_ip=user.client_ip,
    )
    return _ok(result)


@router.post("/alipay")
async def api_alipay_pay(
    body: AlipayPayReq,
    request: Request,
    user: UserContext = Depends(require_role("cashier", "store_manager", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """支付宝支付下单"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await create_alipay_payment(
            order_id=body.order_id,
            amount_fen=body.amount_fen,
            tenant_id=tenant_id,
            buyer_id=body.buyer_id,
            subject=body.subject,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await write_audit(
        db,
        tenant_id=tenant_id,
        store_id=user.store_id,
        user_id=user.user_id,
        user_role=user.role,
        action="payment.alipay.create",
        target_type="order",
        target_id=body.order_id,
        amount_fen=body.amount_fen,
        client_ip=user.client_ip,
    )
    return _ok(result)


@router.post("/unionpay")
async def api_unionpay_pay(
    body: UnionpayPayReq,
    request: Request,
    user: UserContext = Depends(require_role("cashier", "store_manager", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """银联支付下单"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await create_unionpay_payment(
            order_id=body.order_id,
            amount_fen=body.amount_fen,
            tenant_id=tenant_id,
            card_no_masked=body.card_no_masked,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await write_audit(
        db,
        tenant_id=tenant_id,
        store_id=user.store_id,
        user_id=user.user_id,
        user_role=user.role,
        action="payment.unionpay.create",
        target_type="order",
        target_id=body.order_id,
        amount_fen=body.amount_fen,
        client_ip=user.client_ip,
    )
    return _ok(result)


@router.get("/status/{payment_id}")
async def api_query_status(
    payment_id: str,
    request: Request,
    user: UserContext = Depends(require_role("cashier", "store_manager", "admin")),
):
    """查询支付状态（只读，不写审计）"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await query_payment_status(payment_id, tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return _ok(result)


@router.post("/refund")
async def api_refund(
    body: RefundReq,
    request: Request,
    user: UserContext = Depends(require_role("store_manager", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """退款 — 仅店长/管理员可操作（收银员不能直接退）"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await process_refund(
            payment_id=body.payment_id,
            amount_fen=body.amount_fen,
            reason=body.reason,
            tenant_id=tenant_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    await write_audit(
        db,
        tenant_id=tenant_id,
        store_id=user.store_id,
        user_id=user.user_id,
        user_role=user.role,
        action="payment.refund",
        target_type="payment",
        target_id=body.payment_id,
        amount_fen=body.amount_fen,
        client_ip=user.client_ip,
    )
    return _ok(result)


@router.post("/concurrent")
async def api_concurrent_pay(
    body: ConcurrentPayReq,
    request: Request,
    user: UserContext = Depends(require_role("cashier", "store_manager", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """并发支付（多方式同时支付）"""
    tenant_id = _get_tenant_id(request)
    result = await handle_concurrent_payment(
        order_id=body.order_id,
        payments=body.payments,
        tenant_id=tenant_id,
    )
    total = sum(int(p.get("amount_fen", 0) or 0) for p in body.payments)
    await write_audit(
        db,
        tenant_id=tenant_id,
        store_id=user.store_id,
        user_id=user.user_id,
        user_role=user.role,
        action="payment.concurrent",
        target_type="order",
        target_id=body.order_id,
        amount_fen=total or None,
        client_ip=user.client_ip,
    )
    return _ok(result)


@router.post("/risk-check")
async def api_risk_check(
    body: RiskCheckReq,
    request: Request,
    user: UserContext = Depends(require_role("cashier", "store_manager", "admin")),
):
    """风控检查（只读决策，不写审计）"""
    tenant_id = _get_tenant_id(request)
    result = await get_payment_risk_check(
        order_id=body.order_id,
        tenant_id=tenant_id,
        amount_fen=body.amount_fen,
        payment_count_today=body.payment_count_today,
    )
    return _ok(result)
