"""马来西亚业务仪表盘 API 端点 — Phase 3 Sprint 3.3

6 个端点：
  - GET  /api/v1/my/dashboard/sst-summary          SST 汇总
  - GET  /api/v1/my/dashboard/einvoice-stats        e-Invoice 统计
  - GET  /api/v1/my/dashboard/holiday-impact        节假日销售分析
  - GET  /api/v1/my/dashboard/cuisine-performance   菜系表现
  - GET  /api/v1/my/dashboard/subsidies             补贴利用率
  - GET  /api/v1/my/dashboard/multi-currency        多币种报告
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.my_dashboard_service import MYDashboardService

router = APIRouter(prefix="/api/v1/my/dashboard", tags=["my-dashboard"])


# ── DI ──────────────────────────────────────────────────────────


async def get_dashboard_service() -> MYDashboardService:
    return MYDashboardService()


# ── 响应模型 ─────────────────────────────────────────────────────


class SSTSummaryResponse(BaseModel):
    ok: bool = True
    data: dict[str, Any]


class EinvoiceStatsResponse(BaseModel):
    ok: bool = True
    data: dict[str, Any]


class HolidayImpactResponse(BaseModel):
    ok: bool = True
    data: list[dict[str, Any]]


class CuisinePerformanceResponse(BaseModel):
    ok: bool = True
    data: dict[str, Any]


class SubsidiesResponse(BaseModel):
    ok: bool = True
    data: dict[str, Any]


class MultiCurrencyResponse(BaseModel):
    ok: bool = True
    data: dict[str, Any]


# ── 端点 ──────────────────────────────────────────────────────────


@router.get("/sst-summary")
async def get_sst_summary(
    date_from: str = Query(..., description="统计起始日（YYYY-MM-DD）"),
    date_to: str = Query(..., description="统计结束日（YYYY-MM-DD）"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    service: MYDashboardService = Depends(get_dashboard_service),
):
    """SST 汇总报告

    按 SST 分类（6%/8%/0%）统计销售额和应付税款，
    以及月度 SST 应付明细。
    """
    try:
        result = await service.get_sst_summary(
            tenant_id=x_tenant_id,
            period_start=date_from,
            period_end=date_to,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/einvoice-stats")
async def get_einvoice_stats(
    date_from: str = Query(..., description="统计起始日（YYYY-MM-DD）"),
    date_to: str = Query(..., description="统计结束日（YYYY-MM-DD）"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    service: MYDashboardService = Depends(get_dashboard_service),
):
    """e-Invoice 统计报告

    LHDN MyInvois 提交/接受/拒绝统计，月度提交趋势。
    """
    try:
        result = await service.get_einvoice_stats(
            tenant_id=x_tenant_id,
            period_start=date_from,
            period_end=date_to,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/holiday-impact")
async def get_holiday_impact(
    year: int = Query(..., description="目标年份（如 2026）"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    service: MYDashboardService = Depends(get_dashboard_service),
):
    """节假日销售影响分析

    分析全年每个公共假期前后的销售变化，菜系表现。
    包括实际增长与预期增长的对比。
    """
    try:
        result = await service.get_holiday_sales_impact(
            tenant_id=x_tenant_id,
            year=year,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/cuisine-performance")
async def get_cuisine_performance(
    date_from: str = Query(..., description="统计起始日（YYYY-MM-DD）"),
    date_to: str = Query(..., description="统计结束日（YYYY-MM-DD）"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    service: MYDashboardService = Depends(get_dashboard_service),
):
    """菜系经营表现分析

    Malay / Chinese / Indian / Fusion / Borneo 菜系销售拆分，
    各菜系平均订单价、高峰时段、热门菜品 Top 5。
    """
    try:
        result = await service.get_cuisine_performance(
            tenant_id=x_tenant_id,
            period_start=date_from,
            period_end=date_to,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/subsidies")
async def get_subsidies(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    service: MYDashboardService = Depends(get_dashboard_service),
):
    """政府补贴利用率报告

    MDEC / SME Corp 补贴方案的申请情况、节省金额、月度趋势。
    """
    try:
        result = await service.get_subsidy_utilization(
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/multi-currency")
async def get_multi_currency(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    service: MYDashboardService = Depends(get_dashboard_service),
):
    """多币种财务汇总报告

    同时在中国和马来西亚运营的品牌，CNY + MYR 收入汇总。
    """
    try:
        result = await service.get_multi_currency_report(
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
