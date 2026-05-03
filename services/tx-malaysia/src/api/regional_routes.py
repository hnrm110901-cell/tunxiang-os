"""跨区域业务 API 端点 — Phase 3 Sprint 3.6

4 个端点：
  - GET  /api/v1/regional/config                 获取市场区域配置
  - GET  /api/v1/regional/config/{market}        获取指定市场配置
  - GET  /api/v1/regional/consolidated-revenue   多币种汇总收入
  - GET  /api/v1/regional/market-comparison      市场表现对比

所有金额单位为分（fen），与系统 Amount Convention 一致。
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from shared.region.src.cross_border_report import CrossBorderReportService
from shared.region.src.region_config import (
    MarketRegion,
    get_config,
    get_config_by_code,
    get_supported_markets,
    is_market_supported,
)

router = APIRouter(prefix="/api/v1/regional", tags=["regional"])


# ── DI ──────────────────────────────────────────────────────────


async def get_cross_border_service() -> CrossBorderReportService:
    return CrossBorderReportService()


# ── 响应模型 ─────────────────────────────────────────────────────


class RegionConfigResponse(BaseModel):
    ok: bool = True
    data: dict[str, Any]


class ConsolidatedRevenueResponse(BaseModel):
    ok: bool = True
    data: dict[str, Any]


class MarketComparisonResponse(BaseModel):
    ok: bool = True
    data: dict[str, Any]


class SupportedMarketsResponse(BaseModel):
    ok: bool = True
    data: list[dict[str, Any]]


# ── 端点 ──────────────────────────────────────────────────────────


@router.get("/config")
async def list_region_configs(
    include_future: bool = Query(False, description="是否包含未来市场（SG/TH）"),
):
    """获取所有受支持市场的区域配置概览

    返回每个市场的代码、名称、币种、区域设置等信息。
    """
    return {
        "ok": True,
        "data": get_supported_markets(include_future=include_future),
    }


@router.get("/config/{market}")
async def get_region_config(
    market: str,
):
    """获取指定市场的完整区域配置

    包括税率明细、支付方式、外卖平台、发票系统等。

    Args:
        market: 市场代码（如 CN / MY / ID / VN）。
    """
    region = get_config_by_code(market.upper())
    if region is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unsupported market: {market}. "
                   f"Supported: CN, MY, ID, VN",
        )

    return {
        "ok": True,
        "data": {
            "code": region.code.value,
            "name": region.name,
            "currency_code": region.currency_code,
            "currency_symbol": region.currency_symbol,
            "locale": region.locale,
            "timezone": region.timezone,
            "tax_label": region.tax_label,
            "tax_rates": region.tax_rates,
            "payment_methods": region.payment_methods,
            "delivery_platforms": region.delivery_platforms,
            "invoice_system": region.invoice_system,
            "date_format": region.date_format,
            "phone_prefix": region.phone_prefix,
            "language_codes": region.language_codes,
        },
    }


@router.get("/consolidated-revenue")
async def get_consolidated_revenue(
    date_from: str = Query(..., description="统计起始日（YYYY-MM-DD）"),
    date_to: str = Query(..., description="统计结束日（YYYY-MM-DD）"),
    target_currency: str = Query(
        "CNY", description="目标汇总币种（CNY/MYR/IDR/VND/USD）"
    ),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    service: CrossBorderReportService = Depends(get_cross_border_service),
):
    """多币种汇总收入报告

    将所有市场的门店收入按指定币种汇总，支持跨国品牌统一查看
    全渠道收入。

    金额单位：分（fen）。汇总使用固定参考汇率（2026-04-01更新）。
    """
    try:
        result = await service.consolidate_revenue(
            tenant_id=x_tenant_id,
            period_start=date_from,
            period_end=date_to,
            target_currency=target_currency.upper(),
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/market-comparison")
async def get_market_comparison(
    date_from: str = Query(..., description="统计起始日（YYYY-MM-DD）"),
    date_to: str = Query(..., description="统计结束日（YYYY-MM-DD）"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    service: CrossBorderReportService = Depends(get_cross_border_service),
):
    """市场表现对比报告

    比较各市场的收入、交易量、平均订单价、门店数等指标，
    以 USD 为基准币种进行跨市场横向对比。
    """
    try:
        result = await service.compare_market_performance(
            tenant_id=x_tenant_id,
            period_start=date_from,
            period_end=date_to,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
