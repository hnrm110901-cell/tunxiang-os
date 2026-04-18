"""
应用市场 API — 应用广场 / 安装 / 评价 / 计费
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..services.app_marketplace_service import AppMarketplaceService
from ..services.billing_service import BillingService

router = APIRouter(prefix="/api/v1/marketplace", tags=["marketplace"])
logger = structlog.get_logger()


class InstallRequest(BaseModel):
    tier_name: Optional[str] = "basic"
    installed_by: Optional[str] = None


class ChangeTierRequest(BaseModel):
    new_tier: str


class ReviewRequest(BaseModel):
    tenant_id: str
    rating: int = Field(ge=1, le=5)
    review_text: Optional[str] = None
    reviewed_by: Optional[str] = None


class UsageRequest(BaseModel):
    period: str = Field(description="YYYY-MM")
    usage_json: Dict[str, Any]


# ───────────────────── 应用广场 ─────────────────────
@router.get("/apps")
async def list_apps(
    category: Optional[str] = Query(None, description="ai_agent|self_built|third_party|industry_solution"),
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    svc = AppMarketplaceService(db)
    return await svc.list_apps(category=category, search_query=search)


@router.get("/apps/{app_id}")
async def get_app_detail(app_id: str, db: AsyncSession = Depends(get_db)):
    svc = AppMarketplaceService(db)
    detail = await svc.get_app_detail(app_id)
    if not detail:
        raise HTTPException(status_code=404, detail="application not found")
    return detail


# ───────────────────── 安装 / 卸载 / 换档 ─────────────────────
@router.post("/apps/{app_id}/install")
async def install_app(
    app_id: str,
    body: InstallRequest,
    tenant_id: str = Query(..., description="当前租户 ID"),
    db: AsyncSession = Depends(get_db),
):
    svc = AppMarketplaceService(db)
    try:
        res = await svc.install_app(
            tenant_id=tenant_id,
            app_id=app_id,
            tier_name=body.tier_name,
            installed_by=body.installed_by,
        )
        await db.commit()
        return res
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/installations/{installation_id}/uninstall")
async def uninstall(installation_id: str, db: AsyncSession = Depends(get_db)):
    svc = AppMarketplaceService(db)
    ok = await svc.uninstall_app(installation_id)
    if not ok:
        raise HTTPException(status_code=404, detail="installation not found")
    await db.commit()
    return {"installation_id": installation_id, "status": "uninstalled"}


@router.post("/installations/{installation_id}/change-tier")
async def change_tier(
    installation_id: str,
    body: ChangeTierRequest,
    db: AsyncSession = Depends(get_db),
):
    svc = AppMarketplaceService(db)
    try:
        res = await svc.update_tier(installation_id, body.new_tier)
        await db.commit()
        return res
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/installations/my")
async def my_installations(
    tenant_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    svc = AppMarketplaceService(db)
    return await svc.get_my_installations(tenant_id)


# ───────────────────── 评价 ─────────────────────
@router.post("/apps/{app_id}/reviews")
async def submit_review(
    app_id: str,
    body: ReviewRequest,
    db: AsyncSession = Depends(get_db),
):
    svc = AppMarketplaceService(db)
    try:
        res = await svc.submit_review(
            app_id=app_id,
            tenant_id=body.tenant_id,
            rating=body.rating,
            review_text=body.review_text,
            reviewed_by=body.reviewed_by,
        )
        await db.commit()
        return res
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


# ───────────────────── 计费 ─────────────────────
@router.get("/billing/my")
async def my_billing(
    tenant_id: str = Query(...),
    period: str = Query(..., description="YYYY-MM"),
    db: AsyncSession = Depends(get_db),
):
    svc = BillingService(db)
    res = await svc.compute_monthly_invoice(tenant_id, period)
    await db.commit()
    return res


@router.post("/billing/installations/{installation_id}/usage")
async def report_usage(
    installation_id: str,
    body: UsageRequest,
    db: AsyncSession = Depends(get_db),
):
    svc = BillingService(db)
    res = await svc.apply_usage_data(installation_id, body.period, body.usage_json)
    await db.commit()
    return res


@router.get("/billing/installations/{installation_id}/usage-check")
async def check_usage(installation_id: str, db: AsyncSession = Depends(get_db)):
    svc = BillingService(db)
    return await svc.check_usage_exceeded(installation_id)


@router.get("/billing/my.pdf")
async def my_billing_pdf(
    tenant_id: str = Query(...),
    period: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    svc = BillingService(db)
    pdf = await svc.generate_invoice_pdf(tenant_id, period)
    await db.commit()
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="invoice-{tenant_id}-{period}.pdf"'},
    )
