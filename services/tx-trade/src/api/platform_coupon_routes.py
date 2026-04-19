"""平台团购核销 API — 聚合核销(美团/抖音/口碑/广发银行)"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..security.rbac import UserContext, require_role
from ..services import coupon_platform_service as cps
from ..services.trade_audit_log import write_audit

router = APIRouter(
    prefix="/api/v1/trade/platform-coupon",
    tags=["platform-coupon"],
)


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


# ─── 请求模型 ───


class VerifyReq(BaseModel):
    code: str
    store_id: str


class RedeemReq(BaseModel):
    platform: str
    code: str
    order_id: str


class ReportReq(BaseModel):
    store_id: str
    start_date: str
    end_date: str


class ReconcileReq(BaseModel):
    platform: str
    store_id: str
    date: str


# ─── 端点 ───


@router.post("/verify")
async def verify_platform_coupon(
    body: VerifyReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(require_role("cashier", "store_manager", "admin")),
):
    """聚合验证 — 扫码自动识别平台并验证"""
    tenant_id = _get_tenant_id(request)
    result = await cps.aggregate_verify(
        code=body.code,
        store_id=body.store_id,
        tenant_id=tenant_id,
        db=db,
    )
    await write_audit(
        db,
        tenant_id=tenant_id,
        store_id=body.store_id,
        user_id=user.user_id,
        user_role=user.role,
        action="platform_coupon.verify",
        target_type="coupon",
        target_id=None,
        amount_fen=None,
        client_ip=user.client_ip,
    )
    return {"ok": True, "data": result}


@router.post("/redeem")
async def redeem_platform_coupon(
    body: RedeemReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(require_role("cashier", "store_manager", "admin")),
):
    """核销 — 关联 order_id"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await cps.redeem_coupon(
            platform=body.platform,
            code=body.code,
            order_id=body.order_id,
            tenant_id=tenant_id,
            db=db,
        )
        await write_audit(
            db,
            tenant_id=tenant_id,
            store_id=user.store_id,
            user_id=user.user_id,
            user_role=user.role,
            action="platform_coupon.redeem",
            target_type="order",
            target_id=body.order_id,
            amount_fen=None,
            client_ip=user.client_ip,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/report")
async def get_redemption_report(
    store_id: str,
    start_date: str,
    end_date: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(require_role("store_manager", "admin", "auditor", "audit_admin")),
):
    """核销报告 — 按平台/日期汇总（只读）"""
    tenant_id = _get_tenant_id(request)
    result = await cps.get_redemption_report(
        store_id=store_id,
        date_range=(start_date, end_date),
        tenant_id=tenant_id,
        db=db,
    )
    return {"ok": True, "data": result}


@router.post("/reconcile")
async def reconcile_platform(
    body: ReconcileReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(require_role("store_manager", "admin")),
):
    """平台对账 — 平台金额 vs 系统金额"""
    tenant_id = _get_tenant_id(request)
    result = await cps.reconcile_platform(
        platform=body.platform,
        store_id=body.store_id,
        date_str=body.date,
        tenant_id=tenant_id,
        db=db,
    )
    await write_audit(
        db,
        tenant_id=tenant_id,
        store_id=body.store_id,
        user_id=user.user_id,
        user_role=user.role,
        action="platform_coupon.reconcile",
        target_type="reconcile",
        target_id=None,
        amount_fen=None,
        client_ip=user.client_ip,
    )
    return {"ok": True, "data": result}
