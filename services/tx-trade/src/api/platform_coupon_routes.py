"""平台团购核销 API — 聚合核销(美团/抖音/口碑/广发银行)"""
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..services import coupon_platform_service as cps

router = APIRouter(
    prefix="/api/v1/trade/platform-coupon",
    tags=["platform-coupon"],
)


def _get_tenant_id(request: Request) -> str:
    tid = (
        getattr(request.state, "tenant_id", None)
        or request.headers.get("X-Tenant-ID", "")
    )
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
):
    """聚合验证 — 扫码自动识别平台并验证"""
    tenant_id = _get_tenant_id(request)
    result = await cps.aggregate_verify(
        code=body.code,
        store_id=body.store_id,
        tenant_id=tenant_id,
        db=db,
    )
    return {"ok": True, "data": result}


@router.post("/redeem")
async def redeem_platform_coupon(
    body: RedeemReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
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
):
    """核销报告 — 按平台/日期汇总"""
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
    return {"ok": True, "data": result}
