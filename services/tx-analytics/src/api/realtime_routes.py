"""实时经营数据 API — 当日实时指标（每分钟可刷新）

GET /api/v1/analytics/realtime/today          — 当日实时经营数据
GET /api/v1/analytics/realtime/hourly-trend   — 今日每小时营收趋势
GET /api/v1/analytics/realtime/store-comparison — 多门店实时对比
GET /api/v1/analytics/realtime/alerts         — 实时异常告警

RLS 安全：所有 DB 查询均通过 set_config('app.tenant_id', ...) 设置租户上下文。
容错：DB 查询失败时返回空数据结构，不返回 500，保证驾驶舱始终可用。
"""

from datetime import date, datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Header, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from shared.ontology.src.database import async_session_factory

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/analytics/realtime", tags=["analytics-realtime"])


async def _set_tenant(session, tenant_id: str) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


@router.get("/today")
async def get_today_realtime(
    store_id: Optional[str] = Query(None),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    """当日实时经营数据（客流/营收/厨房队列）"""
    today_start = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)
    today_end = datetime.combine(date.today(), datetime.max.time()).replace(tzinfo=timezone.utc)

    try:
        async with async_session_factory() as session:
            await _set_tenant(session, x_tenant_id)

            store_filter = "AND o.store_id = :store_id::uuid" if store_id else ""
            params: dict = {
                "start": today_start,
                "end": today_end,
                "tenant_id": x_tenant_id,
            }
            if store_id:
                params["store_id"] = store_id

            # 营收/订单数/客单价
            summary_row = (
                (
                    await session.execute(
                        text(f"""
                    SELECT
                        COALESCE(SUM(o.final_amount_fen), 0)  AS revenue_fen,
                        COUNT(*) AS order_count,
                        COALESCE(SUM(o.refund_amount_fen), 0) AS refund_fen,
                        COUNT(CASE WHEN o.refund_amount_fen > 0 THEN 1 END) AS refund_count
                    FROM orders o
                    WHERE o.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                      AND o.order_time >= :start
                      AND o.order_time <= :end
                      AND o.status NOT IN ('cancelled', 'voided')
                      AND o.is_deleted = false
                      {store_filter}
                """),
                        params,
                    )
                )
                .mappings()
                .one()
            )

            revenue_fen: int = summary_row["revenue_fen"] or 0
            order_count: int = summary_row["order_count"] or 0
            refund_fen: int = summary_row["refund_fen"] or 0
            refund_count: int = summary_row["refund_count"] or 0
            avg_order_fen: int = revenue_fen // order_count if order_count > 0 else 0

            # 新增会员数（今日注册）
            new_members: int = (
                await session.execute(
                    text("""
                    SELECT COUNT(*) FROM customers
                    WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                      AND created_at >= :start
                      AND created_at <= :end
                      AND is_deleted = false
                """),
                    {"start": today_start, "end": today_end},
                )
            ).scalar() or 0

            # 今日热销 TOP 5 菜品
            top_dishes_rows = (
                (
                    await session.execute(
                        text(f"""
                    SELECT oi.item_name, SUM(oi.quantity) AS cnt
                    FROM order_items oi
                    JOIN orders o ON o.id = oi.order_id
                    WHERE o.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                      AND o.order_time >= :start
                      AND o.order_time <= :end
                      AND o.status NOT IN ('cancelled', 'voided')
                      AND o.is_deleted = false
                      AND oi.is_deleted = false
                      {store_filter}
                    GROUP BY oi.item_name
                    ORDER BY cnt DESC
                    LIMIT 5
                """),
                        params,
                    )
                )
                .mappings()
                .all()
            )

            top_dishes = [{"name": r["item_name"], "count": int(r["cnt"])} for r in top_dishes_rows]

            data = {
                "as_of": datetime.now(tz=timezone.utc).isoformat(),
                "revenue_fen": revenue_fen,
                "order_count": order_count,
                "avg_order_fen": avg_order_fen,
                "refund_count": refund_count,
                "refund_amount_fen": refund_fen,
                "new_members_today": new_members,
                "top_dishes_today": top_dishes,
            }
            log.info(
                "realtime.today",
                tenant=x_tenant_id,
                store_id=store_id,
                order_count=order_count,
                revenue_fen=revenue_fen,
            )
            return {"ok": True, "data": data}

    except SQLAlchemyError as exc:
        log.warning("realtime.today.db_error", tenant=x_tenant_id, error=str(exc))
        return {
            "ok": True,
            "data": {
                "as_of": datetime.now(tz=timezone.utc).isoformat(),
                "revenue_fen": 0,
                "order_count": 0,
                "avg_order_fen": 0,
                "refund_count": 0,
                "refund_amount_fen": 0,
                "new_members_today": 0,
                "top_dishes_today": [],
                "_error": "db_unavailable",
            },
        }


@router.get("/hourly-trend")
async def get_hourly_trend(
    store_id: Optional[str] = Query(None),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    """今日每小时营收趋势"""
    today_start = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)
    today_end = datetime.now(tz=timezone.utc)
    current_hour = today_end.hour

    try:
        async with async_session_factory() as session:
            await _set_tenant(session, x_tenant_id)

            store_filter = "AND o.store_id = :store_id::uuid" if store_id else ""
            params: dict = {
                "start": today_start,
                "end": today_end,
                "tenant_id": x_tenant_id,
            }
            if store_id:
                params["store_id"] = store_id

            rows = (
                (
                    await session.execute(
                        text(f"""
                    SELECT
                        EXTRACT(HOUR FROM o.order_time AT TIME ZONE 'Asia/Shanghai') AS hour,
                        COALESCE(SUM(o.final_amount_fen), 0)                          AS revenue_fen,
                        COUNT(*)                                                       AS order_count
                    FROM orders o
                    WHERE o.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                      AND o.order_time >= :start
                      AND o.order_time <= :end
                      AND o.status NOT IN ('cancelled', 'voided')
                      AND o.is_deleted = false
                      {store_filter}
                    GROUP BY hour
                    ORDER BY hour
                """),
                        params,
                    )
                )
                .mappings()
                .all()
            )

            hours = [
                {
                    "hour": f"{int(r['hour']):02d}:00",
                    "revenue_fen": int(r["revenue_fen"]),
                    "order_count": int(r["order_count"]),
                }
                for r in rows
            ]
            log.info("realtime.hourly_trend", tenant=x_tenant_id, store_id=store_id, hours_count=len(hours))
            return {"ok": True, "data": {"hours": hours, "current_hour": current_hour}}

    except SQLAlchemyError as exc:
        log.warning("realtime.hourly_trend.db_error", tenant=x_tenant_id, error=str(exc))
        return {"ok": True, "data": {"hours": [], "current_hour": current_hour, "_error": "db_unavailable"}}


@router.get("/store-comparison")
async def get_store_comparison(
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    """多门店实时对比（今日数据）"""
    today_start = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)
    today_end = datetime.now(tz=timezone.utc)

    try:
        async with async_session_factory() as session:
            await _set_tenant(session, x_tenant_id)

            rows = (
                (
                    await session.execute(
                        text("""
                    SELECT
                        s.store_name,
                        COALESCE(SUM(o.final_amount_fen), 0) AS revenue_fen,
                        COUNT(o.id)                          AS order_count
                    FROM stores s
                    LEFT JOIN orders o
                        ON o.store_id = s.id
                       AND o.order_time >= :start
                       AND o.order_time <= :end
                       AND o.status NOT IN ('cancelled', 'voided')
                       AND o.is_deleted = false
                    WHERE s.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                      AND s.is_deleted = false
                    GROUP BY s.id, s.store_name
                    ORDER BY revenue_fen DESC
                    LIMIT 20
                """),
                        {"start": today_start, "end": today_end},
                    )
                )
                .mappings()
                .all()
            )

            stores = [
                {
                    "store_name": r["store_name"],
                    "revenue_fen": int(r["revenue_fen"]),
                    "order_count": int(r["order_count"]),
                }
                for r in rows
            ]
            log.info("realtime.store_comparison", tenant=x_tenant_id, stores_count=len(stores))
            return {"ok": True, "data": {"stores": stores}}

    except SQLAlchemyError as exc:
        log.warning("realtime.store_comparison.db_error", tenant=x_tenant_id, error=str(exc))
        return {"ok": True, "data": {"stores": [], "_error": "db_unavailable"}}


@router.get("/alerts")
async def get_realtime_alerts(
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    """实时异常告警（今日，未解决）

    告警由 tx-agent 折扣守护/出餐调度等 Skill Agent 写入 analytics_alerts 表。
    若表不存在（尚未部署），返回空列表。
    """
    today_start = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)

    try:
        async with async_session_factory() as session:
            await _set_tenant(session, x_tenant_id)

            rows = (
                (
                    await session.execute(
                        text("""
                    SELECT
                        aa.severity   AS level,
                        aa.alert_type AS type,
                        aa.message,
                        s.store_name  AS store,
                        aa.created_at AS at
                    FROM analytics_alerts aa
                    LEFT JOIN stores s ON s.id = aa.store_id AND s.is_deleted = false
                    WHERE aa.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                      AND aa.created_at >= :today_start
                      AND aa.resolved = false
                      AND aa.is_deleted = false
                    ORDER BY aa.severity DESC, aa.created_at DESC
                    LIMIT 50
                """),
                        {"today_start": today_start},
                    )
                )
                .mappings()
                .all()
            )

            alerts = [
                {
                    "level": r["level"],
                    "type": r["type"],
                    "message": r["message"],
                    "store": r["store"] or "",
                    "at": r["at"].isoformat() if r["at"] else "",
                }
                for r in rows
            ]
            log.info("realtime.alerts", tenant=x_tenant_id, count=len(alerts))
            return {"ok": True, "data": {"alerts": alerts}}

    except SQLAlchemyError as exc:
        log.warning("realtime.alerts.db_error", tenant=x_tenant_id, error=str(exc))
        # analytics_alerts 表可能尚未部署，返回空列表而非 500
        return {"ok": True, "data": {"alerts": [], "_error": "db_unavailable"}}
