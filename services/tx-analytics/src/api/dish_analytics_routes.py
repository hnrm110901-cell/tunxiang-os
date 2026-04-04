"""菜品经营分析 API — 销售排名 / 时段热力 / 低效菜品预警

GET /api/v1/analytics/dishes/top-selling      — 热销菜品排行（真实销量）
GET /api/v1/analytics/dishes/time-heatmap     — 菜品销售时段热力图
GET /api/v1/analytics/dishes/pairing-analysis — 常点搭配分析
GET /api/v1/analytics/dishes/underperforming  — 低销量/低毛利菜品预警

RLS 安全：所有查询通过 set_config('app.tenant_id', ...) 设置租户上下文。
容错：DB 查询失败时返回空数组，不返回 500。
"""
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Header, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from shared.ontology.src.database import async_session_factory

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/analytics/dishes", tags=["analytics-dishes"])


async def _set_tenant(session, tenant_id: str) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


@router.get("/top-selling")
async def top_selling_dishes(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(10, ge=1, le=100),
    store_id: Optional[str] = Query(None),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    """热销菜品排行（按销售数量降序）"""
    start_dt = datetime.combine(
        date.today() - timedelta(days=days - 1),
        datetime.min.time(),
    ).replace(tzinfo=timezone.utc)

    try:
        async with async_session_factory() as session:
            await _set_tenant(session, x_tenant_id)

            store_filter = "AND o.store_id = :store_id::uuid" if store_id else ""
            params: dict = {"start_dt": start_dt, "limit": limit}
            if store_id:
                params["store_id"] = store_id

            rows = (await session.execute(
                text(f"""
                    SELECT
                        COALESCE(d.id::text, '')             AS dish_id,
                        oi.item_name                         AS dish_name,
                        COALESCE(dc.name, '未分类')           AS category,
                        SUM(oi.quantity)                     AS sales_count,
                        SUM(oi.subtotal_fen)                 AS revenue_fen,
                        ROUND(SUM(oi.quantity)::numeric / :days_count, 1) AS avg_daily_count
                    FROM order_items oi
                    JOIN orders o ON o.id = oi.order_id
                    LEFT JOIN dishes d ON d.id = oi.dish_id AND d.is_deleted = false
                    LEFT JOIN dish_categories dc ON dc.id = d.category_id AND dc.is_deleted = false
                    WHERE o.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                      AND o.order_time >= :start_dt
                      AND o.status NOT IN ('cancelled', 'voided')
                      AND o.is_deleted = false
                      AND oi.is_deleted = false
                      {store_filter}
                    GROUP BY d.id, oi.item_name, dc.name
                    ORDER BY sales_count DESC
                    LIMIT :limit
                """),
                {**params, "days_count": days},
            )).mappings().all()

            dishes = [
                {
                    "dish_id": r["dish_id"],
                    "dish_name": r["dish_name"],
                    "category": r["category"],
                    "sales_count": int(r["sales_count"]),
                    "revenue_fen": int(r["revenue_fen"]),
                    "avg_daily_count": float(r["avg_daily_count"]),
                }
                for r in rows
            ]
            log.info("dishes.top_selling", tenant=x_tenant_id, days=days,
                     store_id=store_id, count=len(dishes))
            return {"ok": True, "data": {"period_days": days, "dishes": dishes}}

    except SQLAlchemyError as exc:
        log.warning("dishes.top_selling.db_error", tenant=x_tenant_id, error=str(exc))
        return {"ok": True, "data": {"period_days": days, "dishes": [], "_error": "db_unavailable"}}


@router.get("/time-heatmap")
async def dish_time_heatmap(
    dish_id: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=365),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    """菜品销售时段热力图（小时×星期，基于真实订单数据）"""
    start_dt = datetime.combine(
        date.today() - timedelta(days=days - 1),
        datetime.min.time(),
    ).replace(tzinfo=timezone.utc)

    try:
        async with async_session_factory() as session:
            await _set_tenant(session, x_tenant_id)

            dish_filter = "AND oi.dish_id = :dish_id::uuid" if dish_id else ""
            params: dict = {"start_dt": start_dt}
            if dish_id:
                params["dish_id"] = dish_id

            rows = (await session.execute(
                text(f"""
                    SELECT
                        -- 0=周一 … 6=周日（ISO: 1=Mon, 7=Sun）
                        (EXTRACT(ISODOW FROM o.order_time AT TIME ZONE 'Asia/Shanghai') - 1)::int
                            AS day_of_week,
                        EXTRACT(HOUR FROM o.order_time AT TIME ZONE 'Asia/Shanghai')::int
                            AS hour,
                        SUM(oi.quantity) AS count
                    FROM order_items oi
                    JOIN orders o ON o.id = oi.order_id
                    WHERE o.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                      AND o.order_time >= :start_dt
                      AND o.status NOT IN ('cancelled', 'voided')
                      AND o.is_deleted = false
                      AND oi.is_deleted = false
                      {dish_filter}
                    GROUP BY day_of_week, hour
                    ORDER BY day_of_week, hour
                """),
                params,
            )).mappings().all()

            # 构建稀疏→稠密热力图（补零）
            heat_index: dict[tuple[int, int], float] = {
                (int(r["day_of_week"]), int(r["hour"])): float(r["count"])
                for r in rows
            }
            heatmap = [
                {
                    "day_of_week": dow,
                    "hour": h,
                    "count": heat_index.get((dow, h), 0.0),
                }
                for dow in range(7)
                for h in range(24)
            ]
            log.info("dishes.time_heatmap", tenant=x_tenant_id, dish_id=dish_id,
                     nonzero_cells=len(rows))
            return {"ok": True, "data": {"heatmap": heatmap}}

    except SQLAlchemyError as exc:
        log.warning("dishes.time_heatmap.db_error", tenant=x_tenant_id, error=str(exc))
        return {"ok": True, "data": {"heatmap": [], "_error": "db_unavailable"}}


@router.get("/pairing-analysis")
async def dish_pairing(
    dish_id: str = Query(...),
    days: int = Query(30, ge=1, le=365),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    """常点搭配分析（同一订单内同时点的其他菜品）"""
    start_dt = datetime.combine(
        date.today() - timedelta(days=days - 1),
        datetime.min.time(),
    ).replace(tzinfo=timezone.utc)

    try:
        async with async_session_factory() as session:
            await _set_tenant(session, x_tenant_id)

            # 找出与 dish_id 同单的其他菜品及共现次数
            rows = (await session.execute(
                text("""
                    WITH target_orders AS (
                        SELECT DISTINCT oi.order_id
                        FROM order_items oi
                        JOIN orders o ON o.id = oi.order_id
                        WHERE oi.dish_id = :dish_id::uuid
                          AND o.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                          AND o.order_time >= :start_dt
                          AND o.status NOT IN ('cancelled', 'voided')
                          AND o.is_deleted = false
                          AND oi.is_deleted = false
                    ),
                    total_count AS (SELECT COUNT(*) AS n FROM target_orders)
                    SELECT
                        oi2.item_name        AS dish_name,
                        COUNT(*)             AS count,
                        ROUND(COUNT(*)::numeric / NULLIF((SELECT n FROM total_count), 0), 4)
                            AS co_occurrence_rate
                    FROM target_orders t
                    JOIN order_items oi2 ON oi2.order_id = t.order_id
                    WHERE oi2.dish_id != :dish_id::uuid
                      AND oi2.is_deleted = false
                    GROUP BY oi2.item_name
                    ORDER BY count DESC
                    LIMIT 10
                """),
                {"dish_id": dish_id, "start_dt": start_dt},
            )).mappings().all()

            pairings = [
                {
                    "dish_name": r["dish_name"],
                    "count": int(r["count"]),
                    "co_occurrence_rate": float(r["co_occurrence_rate"] or 0),
                }
                for r in rows
            ]
            log.info("dishes.pairing", tenant=x_tenant_id, dish_id=dish_id,
                     pairings_count=len(pairings))
            return {"ok": True, "data": {"dish_id": dish_id, "pairings": pairings}}

    except SQLAlchemyError as exc:
        log.warning("dishes.pairing.db_error", tenant=x_tenant_id, error=str(exc))
        return {"ok": True, "data": {"dish_id": dish_id, "pairings": [], "_error": "db_unavailable"}}


@router.get("/underperforming")
async def underperforming_dishes(
    days: int = Query(30, ge=1, le=365),
    min_sales_threshold: int = Query(20, description="低于此销量视为低销量"),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    """低销量菜品预警（适合下架或加强推广建议）

    策略：统计期内销量低于阈值的菜品，按销量升序排列。
    毛利数据依赖 dish_ingredients + ingredient 成本，若未录入则不展示毛利维度。
    """
    start_dt = datetime.combine(
        date.today() - timedelta(days=days - 1),
        datetime.min.time(),
    ).replace(tzinfo=timezone.utc)

    try:
        async with async_session_factory() as session:
            await _set_tenant(session, x_tenant_id)

            rows = (await session.execute(
                text("""
                    SELECT
                        COALESCE(d.id::text, '') AS dish_id,
                        oi.item_name             AS dish_name,
                        COALESCE(dc.name, '未分类') AS category,
                        SUM(oi.quantity)         AS sales_count,
                        SUM(oi.subtotal_fen)     AS revenue_fen
                    FROM order_items oi
                    JOIN orders o ON o.id = oi.order_id
                    LEFT JOIN dishes d ON d.id = oi.dish_id AND d.is_deleted = false
                    LEFT JOIN dish_categories dc ON dc.id = d.category_id AND dc.is_deleted = false
                    WHERE o.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                      AND o.order_time >= :start_dt
                      AND o.status NOT IN ('cancelled', 'voided')
                      AND o.is_deleted = false
                      AND oi.is_deleted = false
                    GROUP BY d.id, oi.item_name, dc.name
                    HAVING SUM(oi.quantity) < :threshold
                    ORDER BY sales_count ASC
                    LIMIT 50
                """),
                {"start_dt": start_dt, "threshold": min_sales_threshold},
            )).mappings().all()

            items = [
                {
                    "dish_id": r["dish_id"],
                    "dish_name": r["dish_name"],
                    "category": r["category"],
                    "sales_count": int(r["sales_count"]),
                    "revenue_fen": int(r["revenue_fen"]),
                    "suggestion": "销量偏低，建议加强推广或评估下架",
                }
                for r in rows
            ]
            log.info("dishes.underperforming", tenant=x_tenant_id, days=days,
                     threshold=min_sales_threshold, count=len(items))
            return {"ok": True, "data": {"items": items, "period_days": days}}

    except SQLAlchemyError as exc:
        log.warning("dishes.underperforming.db_error", tenant=x_tenant_id, error=str(exc))
        return {"ok": True, "data": {"items": [], "period_days": days, "_error": "db_unavailable"}}
