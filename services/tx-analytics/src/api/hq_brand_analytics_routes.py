"""HQ跨品牌分析 API 路由

总部视角：三品牌（尝在一起、最黔线、尚宫厨）跨品牌对比与门店绩效矩阵

端点：
  GET /api/v1/analytics/hq/brands/overview            — 品牌总览（营收/单量/健康分）
  GET /api/v1/analytics/hq/brands/{brand_id}/stores/performance — 门店绩效矩阵
  GET /api/v1/analytics/hq/brands/compare             — 多品牌四维对标 + 趋势折线
  GET /api/v1/analytics/hq/brands/{brand_id}/pnl      — 品牌月度P&L

RLS安全：X-Tenant-ID header → set_config('app.tenant_id', ...)
响应格式：{"ok": true, "data": {...}} | {"ok": false, "error": {"message": "..."}}
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from shared.ontology.src.database import async_session_factory

from ..services.hq_brand_analytics_service import HQBrandAnalyticsService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/analytics/hq", tags=["hq-brand-analytics"])

_svc = HQBrandAnalyticsService()


# ─── 内部辅助 ─────────────────────────────────────────────────────────────────

def _require_tenant(tenant_id: Optional[str]) -> str:
    """校验并返回 tenant_id，格式错误抛 400。"""
    if not tenant_id or not tenant_id.strip():
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    try:
        uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID must be a valid UUID")
    return tenant_id.strip()


def _parse_uuid(val: str, field: str) -> uuid.UUID:
    """解析 UUID，格式错误抛 400。"""
    try:
        return uuid.UUID(val)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field} must be a valid UUID, got: {val!r}")


def _parse_brand_ids(raw: Optional[str]) -> list[uuid.UUID] | None:
    """解析逗号分隔的 brand_ids 字符串，返回 UUID 列表或 None。"""
    if not raw or not raw.strip():
        return None
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    result: list[uuid.UUID] = []
    for p in parts:
        try:
            result.append(uuid.UUID(p))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"brand_ids 包含非法UUID：{p!r}")
    return result or None


async def _set_tenant(session, tenant_id: str) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _err(message: str) -> dict:
    return {"ok": False, "error": {"message": message}}


# ─── GET /api/v1/analytics/hq/brands/overview ────────────────────────────────


@router.get("/brands/overview")
async def get_brands_overview(
    date_range: str = Query("today", pattern="^(today|week|month)$"),
    brand_ids: Optional[str] = Query(None, description="逗号分隔的品牌UUID列表，不填返回所有品牌"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """品牌总览 — 每个品牌的营收/单量/健康分汇总

    Query参数：
      date_range  — today（默认）| week | month
      brand_ids   — 逗号分隔的品牌UUID，不填返回租户下所有品牌

    Response：
      {"ok": true, "data": {"brands": [...], "date_range": "week"}}
    """
    tenant_id = _require_tenant(x_tenant_id)
    tenant_uuid = uuid.UUID(tenant_id)
    parsed_brand_ids = _parse_brand_ids(brand_ids)

    try:
        async with async_session_factory() as db:
            await _set_tenant(db, tenant_id)
            brands = await _svc.get_brands_overview(
                db=db,
                tenant_ids=[tenant_uuid],
                date_range=date_range,
                brand_ids=parsed_brand_ids,
            )
    except SQLAlchemyError as exc:
        logger.error(
            "hq_brand_analytics.overview.db_error",
            tenant_id=tenant_id,
            error=str(exc),
        )
        return _err("数据库查询失败，请稍后重试")

    return {"ok": True, "data": {"brands": brands, "date_range": date_range}}


# ─── GET /api/v1/analytics/hq/brands/{brand_id}/stores/performance ───────────


@router.get("/brands/{brand_id}/stores/performance")
async def get_brand_store_performance(
    brand_id: str,
    date: Optional[str] = Query(None, description="YYYY-MM-DD，默认今日"),
    sort_by: str = Query("revenue_fen", pattern="^(revenue_fen|revenue_achievement_pct|gross_margin_pct|rank)$"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """门店绩效矩阵 — 指定品牌下所有门店当日绩效排行

    Path参数：
      brand_id   — 品牌UUID

    Query参数：
      date       — YYYY-MM-DD，默认今日
      sort_by    — revenue_fen（默认）| revenue_achievement_pct | gross_margin_pct | rank
      page       — 页码，默认1
      size       — 每页条数，默认20，最大100

    Response：
      {"ok": true, "data": {"items": [...], "total": int, "page": 1, "size": 20, "brand_id": "..."}}
    """
    tenant_id = _require_tenant(x_tenant_id)
    tenant_uuid = uuid.UUID(tenant_id)
    brand_uuid = _parse_uuid(brand_id, "brand_id")

    # 解析日期
    if date:
        try:
            snapshot_date = _parse_date_str(date)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"date 格式错误，需为 YYYY-MM-DD，实际值：{date!r}")
    else:
        from datetime import date as date_cls
        snapshot_date = date_cls.today()

    try:
        async with async_session_factory() as db:
            await _set_tenant(db, tenant_id)
            result = await _svc.get_brand_store_performance(
                db=db,
                tenant_ids=[tenant_uuid],
                brand_id=brand_uuid,
                snapshot_date=snapshot_date,
                sort_by=sort_by,
                page=page,
                size=size,
            )
    except SQLAlchemyError as exc:
        logger.error(
            "hq_brand_analytics.store_performance.db_error",
            tenant_id=tenant_id,
            brand_id=brand_id,
            error=str(exc),
        )
        return _err("数据库查询失败，请稍后重试")

    return {
        "ok": True,
        "data": {
            **result,
            "brand_id": brand_id,
            "snapshot_date": snapshot_date.isoformat(),
        },
    }


# ─── GET /api/v1/analytics/hq/brands/compare ─────────────────────────────────


@router.get("/brands/compare")
async def compare_brands(
    brand_ids: str = Query(..., description="逗号分隔的品牌UUID列表，至少2个"),
    period: str = Query("week", pattern="^(week|month)$"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """多品牌四维对标 + 7天营收趋势折线图

    Query参数：
      brand_ids  — 必填，逗号分隔的品牌UUID（至少2个）
      period     — week（默认）| month

    Response：
      {
        "ok": true,
        "data": {
          "dimensions": [
            {"dimension": "revenue", "rankings": [{"brand_id":..., "value":..., "rank":1}, ...]},
            ...
          ],
          "trend": {"dates": [...], "brands": {"<brand_id>": [<rev_fen>, ...], ...}}
        }
      }
    """
    tenant_id = _require_tenant(x_tenant_id)
    tenant_uuid = uuid.UUID(tenant_id)
    parsed_brand_ids = _parse_brand_ids(brand_ids)
    if not parsed_brand_ids:
        raise HTTPException(status_code=400, detail="brand_ids 不能为空")
    if len(parsed_brand_ids) < 2:
        raise HTTPException(status_code=400, detail="brand_ids 至少需要2个品牌进行对比")

    try:
        async with async_session_factory() as db:
            await _set_tenant(db, tenant_id)
            result = await _svc.compare_brands(
                db=db,
                tenant_ids=[tenant_uuid],
                brand_ids=parsed_brand_ids,
                period=period,
            )
    except SQLAlchemyError as exc:
        logger.error(
            "hq_brand_analytics.compare_brands.db_error",
            tenant_id=tenant_id,
            error=str(exc),
        )
        return _err("数据库查询失败，请稍后重试")

    return {"ok": True, "data": result}


# ─── GET /api/v1/analytics/hq/brands/{brand_id}/pnl ─────────────────────────


@router.get("/brands/{brand_id}/pnl")
async def get_brand_pnl(
    brand_id: str,
    year_month: str = Query(..., description="月份，格式 YYYY-MM，例如 2026-04"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """品牌月度P&L — 品牌汇总 + 各门店明细

    Path参数：
      brand_id   — 品牌UUID

    Query参数：
      year_month — YYYY-MM 格式月份（必填）

    Response：
      {
        "ok": true,
        "data": {
          "year_month": "2026-04",
          "summary": {revenue_fen, cost_fen, gross_profit_fen, gross_margin_pct,
                      net_profit_fen, net_margin_pct} | null,
          "stores": [{store_id, revenue_fen, ...}]
        }
      }
    """
    tenant_id = _require_tenant(x_tenant_id)
    tenant_uuid = uuid.UUID(tenant_id)
    brand_uuid = _parse_uuid(brand_id, "brand_id")

    # 校验 year_month 格式
    import re
    if not re.fullmatch(r"\d{4}-\d{2}", year_month):
        raise HTTPException(status_code=400, detail=f"year_month 格式错误，需为 YYYY-MM，实际值：{year_month!r}")

    try:
        async with async_session_factory() as db:
            await _set_tenant(db, tenant_id)
            result = await _svc.get_brand_pnl(
                db=db,
                tenant_ids=[tenant_uuid],
                brand_id=brand_uuid,
                year_month=year_month,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SQLAlchemyError as exc:
        logger.error(
            "hq_brand_analytics.brand_pnl.db_error",
            tenant_id=tenant_id,
            brand_id=brand_id,
            year_month=year_month,
            error=str(exc),
        )
        return _err("数据库查询失败，请稍后重试")

    return {"ok": True, "data": result}


# ─── 私有工具 ─────────────────────────────────────────────────────────────────

def _parse_date_str(date_str: str) -> date:
    """将 YYYY-MM-DD 字符串解析为 date 对象，失败抛 ValueError。"""
    from datetime import date as date_cls
    return date_cls.fromisoformat(date_str)
