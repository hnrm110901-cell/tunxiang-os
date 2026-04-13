"""区域经营总览 API 路由

前缀: /api/v1/analytics/region-overview

端点:
  GET  /                       — 区域/品牌维度汇总数据
  GET  /{region_id}/stores     — 区域内门店列表
"""
from __future__ import annotations

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/analytics/region-overview", tags=["region-overview"])


# ─── 指标中文名 ──────────────────────────────────────────────
_METRIC_LABELS = {
    "revenue_fen": "营收（分）",
    "avg_ticket_fen": "客单价（分）",
    "turnover_rate": "翻台率",
    "gross_margin": "毛利率",
    "labor_efficiency_fen": "人效（分/人/天）",
    "complaint_rate": "客诉率",
}


# ─── 辅助函数 ────────────────────────────────────────────────

def _require_tenant(x_tenant_id: Optional[str]) -> uuid.UUID:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID must be a valid UUID")


async def _set_tenant(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


# ─── 端点 ────────────────────────────────────────────────────

@router.get("/")
async def region_overview(
    dimension: str = Query("region", description="维度: region / brand"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """区域/品牌维度汇总数据"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("region_overview", tenant_id=str(tenant_id), dimension=dimension)

    try:
        await _set_tenant(db, tenant_id)

        if dimension == "brand":
            # 按品牌聚合：group stores by brand_id, join orders for revenue
            rows = await db.execute(text("""
                SELECT
                    s.brand_id,
                    COUNT(DISTINCT s.id)                        AS store_count,
                    COALESCE(SUM(o.final_amount_fen), 0)        AS revenue_fen,
                    s.region
                FROM stores s
                LEFT JOIN orders o
                    ON o.store_id = s.id
                    AND o.status  = 'paid'
                    AND o.is_deleted = false
                WHERE s.is_deleted = false
                  AND s.status     = 'active'
                GROUP BY s.brand_id, s.region
            """))
            raw = rows.fetchall()

            brand_map: dict[str, dict] = {}
            for r in raw:
                brand = r.brand_id or "unknown"
                if brand not in brand_map:
                    brand_map[brand] = {
                        "brand": brand,
                        "store_count": 0,
                        "revenue_fen": 0,
                        "regions": [],
                    }
                brand_map[brand]["store_count"] += r.store_count
                brand_map[brand]["revenue_fen"]  += r.revenue_fen
                if r.region and r.region not in brand_map[brand]["regions"]:
                    brand_map[brand]["regions"].append(r.region)

            return {
                "ok": True,
                "data": {
                    "dimension": "brand",
                    "items": list(brand_map.values()),
                    "total": len(brand_map),
                },
            }

        # ── 按区域汇总 ───────────────────────────────────────────────
        # Group stores by the `region` varchar field; join orders for revenue/metrics
        region_rows = await db.execute(text("""
            SELECT
                COALESCE(s.region, '未分区')                    AS region_name,
                COUNT(DISTINCT s.id)                            AS store_count,
                COALESCE(SUM(o.final_amount_fen), 0)            AS revenue_fen,
                COALESCE(SUM(o.guest_count), 0)                 AS total_guests,
                COUNT(o.id)                                     AS order_count,
                CASE WHEN COUNT(o.id) > 0
                     THEN COALESCE(SUM(o.final_amount_fen), 0)::float / COUNT(o.id)
                     ELSE 0 END                                 AS avg_ticket_fen
            FROM stores s
            LEFT JOIN orders o
                ON o.store_id    = s.id
                AND o.status     = 'paid'
                AND o.is_deleted = false
            WHERE s.is_deleted = false
              AND s.status     = 'active'
            GROUP BY COALESCE(s.region, '未分区')
            ORDER BY revenue_fen DESC
        """))
        region_raw = region_rows.fetchall()

        # Per-region brand breakdown
        brand_rows = await db.execute(text("""
            SELECT
                COALESCE(s.region, '未分区')                    AS region_name,
                COALESCE(s.brand_id, 'unknown')                 AS brand,
                COUNT(DISTINCT s.id)                            AS store_count,
                COALESCE(SUM(o.final_amount_fen), 0)            AS revenue_fen
            FROM stores s
            LEFT JOIN orders o
                ON o.store_id    = s.id
                AND o.status     = 'paid'
                AND o.is_deleted = false
            WHERE s.is_deleted = false
              AND s.status     = 'active'
            GROUP BY COALESCE(s.region, '未分区'), COALESCE(s.brand_id, 'unknown')
        """))
        brand_raw = brand_rows.fetchall()

        # Build brand lookup keyed by region
        brand_by_region: dict[str, list] = {}
        for br in brand_raw:
            brand_by_region.setdefault(br.region_name, []).append({
                "brand":       br.brand,
                "store_count": br.store_count,
                "revenue_fen": br.revenue_fen,
            })

        items = []
        for r in region_raw:
            items.append({
                "region_id":   r.region_name,   # use region name as stable key
                "region_name": r.region_name,
                "store_count": r.store_count,
                "metrics": {
                    "revenue_fen":   r.revenue_fen,
                    "avg_ticket_fen": int(r.avg_ticket_fen),
                    "order_count":   r.order_count,
                    "total_guests":  r.total_guests,
                },
                "brands": brand_by_region.get(r.region_name, []),
            })

        total_revenue = sum(i["metrics"]["revenue_fen"] for i in items)
        total_stores  = sum(i["store_count"] for i in items)

        return {
            "ok": True,
            "data": {
                "dimension": "region",
                "items": items,
                "total": len(items),
                "group_summary": {
                    "total_stores":    total_stores,
                    "total_revenue_fen": total_revenue,
                    "metric_labels":   _METRIC_LABELS,
                },
            },
        }

    except SQLAlchemyError as exc:
        logger.error("region_overview.db_error", error=str(exc))
        return {
            "ok": True,
            "data": {
                "dimension": dimension,
                "items": [],
                "total": 0,
                "group_summary": {
                    "total_stores": 0,
                    "total_revenue_fen": 0,
                    "metric_labels": _METRIC_LABELS,
                },
            },
        }


@router.get("/{region_id}/stores")
async def region_stores(
    region_id: str,
    sort_by: str = Query("revenue_fen", description="排序: revenue_fen/store_name"),
    sort_order: str = Query("desc", description="排序方向: asc/desc"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """区域内门店列表"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("region_stores", tenant_id=str(tenant_id), region_id=region_id)

    try:
        await _set_tenant(db, tenant_id)

        # Verify the region exists (region_id is the region string value)
        check = await db.execute(text("""
            SELECT COUNT(*)
            FROM stores
            WHERE is_deleted = false
              AND status     = 'active'
              AND COALESCE(region, '未分区') = :region_id
        """), {"region_id": region_id})
        total = check.scalar() or 0
        if total == 0:
            raise HTTPException(status_code=404, detail=f"区域不存在: {region_id}")

        # Ordering
        allowed_sorts = {"revenue_fen", "store_name"}
        if sort_by not in allowed_sorts:
            sort_by = "revenue_fen"
        direction = "DESC" if sort_order == "desc" else "ASC"
        offset = (page - 1) * size

        rows = await db.execute(text(f"""
            SELECT
                s.id::text                                      AS store_id,
                s.store_name,
                s.city,
                s.brand_id,
                COALESCE(SUM(o.final_amount_fen), 0)            AS revenue_fen,
                COUNT(o.id)                                     AS order_count
            FROM stores s
            LEFT JOIN orders o
                ON o.store_id    = s.id
                AND o.status     = 'paid'
                AND o.is_deleted = false
            WHERE s.is_deleted = false
              AND s.status     = 'active'
              AND COALESCE(s.region, '未分区') = :region_id
            GROUP BY s.id, s.store_name, s.city, s.brand_id
            ORDER BY {sort_by} {direction}
            LIMIT :size OFFSET :offset
        """), {"region_id": region_id, "size": size, "offset": offset})
        store_rows = rows.fetchall()

        items = [
            {
                "store_id":    r.store_id,
                "store_name":  r.store_name,
                "city":        r.city,
                "brand_id":    r.brand_id,
                "revenue_fen": r.revenue_fen,
                "order_count": r.order_count,
            }
            for r in store_rows
        ]

        return {
            "ok": True,
            "data": {
                "region_id":   region_id,
                "region_name": region_id,
                "items":  items,
                "total":  total,
                "page":   page,
                "size":   size,
            },
        }

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("region_stores.db_error", error=str(exc))
        return {
            "ok": True,
            "data": {
                "region_id":   region_id,
                "region_name": region_id,
                "items":  [],
                "total":  0,
                "page":   page,
                "size":   size,
            },
        }
