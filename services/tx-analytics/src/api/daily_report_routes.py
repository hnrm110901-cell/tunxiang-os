"""经营日报 API — 预计算日报查询 / 手动生成 / 多日汇总

GET  /api/v1/analytics/daily-reports            — 日报列表（支持日期范围筛选）
GET  /api/v1/analytics/daily-reports/summary     — 多日汇总（周/月维度）
GET  /api/v1/analytics/daily-reports/{date}      — 单日详情
POST /api/v1/analytics/daily-reports/generate    — 手动触发生成（预留）

数据源：直接从 orders / order_items 表聚合，无需预计算表。
RLS 安全：所有查询通过 set_config('app.tenant_id', ...) 设置租户上下文。
容错：DB 查询失败时返回空结构，不返回 500。
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from shared.ontology.src.database import async_session_factory

log = structlog.get_logger()
router = APIRouter(
    prefix="/api/v1/analytics/daily-reports",
    tags=["analytics-daily-reports"],
)


async def _set_tenant(session, tenant_id: str) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _day_window_utc(d: date) -> tuple[datetime, datetime]:
    start = datetime.combine(d, datetime.min.time()).replace(tzinfo=timezone.utc)
    end = datetime.combine(d, datetime.max.time()).replace(tzinfo=timezone.utc)
    return start, end


async def _query_daily_report(session, d: date, store_id: Optional[str]) -> dict:
    """从 orders 表聚合单日报表数据。"""
    day_start, day_end = _day_window_utc(d)
    store_filter = "AND o.store_id = :store_id::uuid" if store_id else ""
    params: dict = {"start": day_start, "end": day_end}
    if store_id:
        params["store_id"] = store_id

    # 核心聚合
    row = (
        (
            await session.execute(
                text(f"""
            SELECT
                COUNT(*)                              AS order_count,
                COALESCE(SUM(o.final_amount_fen), 0)  AS revenue_fen,
                COUNT(DISTINCT o.store_id)            AS store_count
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

    order_count: int = row["order_count"] or 0
    revenue_fen: int = row["revenue_fen"] or 0
    avg_ticket_fen: int = revenue_fen // order_count if order_count > 0 else 0

    # 支付方式分布
    pay_rows = (
        (
            await session.execute(
                text(f"""
            SELECT
                COALESCE(o.payment_method, 'other') AS method,
                SUM(o.final_amount_fen)             AS amount_fen
            FROM orders o
            WHERE o.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
              AND o.order_time >= :start
              AND o.order_time <= :end
              AND o.status NOT IN ('cancelled', 'voided')
              AND o.is_deleted = false
              {store_filter}
            GROUP BY o.payment_method
        """),
                params,
            )
        )
        .mappings()
        .all()
    )
    payment_breakdown = {r["method"]: int(r["amount_fen"] or 0) for r in pay_rows}

    # 渠道分布
    channel_rows = (
        (
            await session.execute(
                text(f"""
            SELECT
                COALESCE(o.order_type, 'other') AS channel,
                SUM(o.final_amount_fen)         AS amount_fen
            FROM orders o
            WHERE o.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
              AND o.order_time >= :start
              AND o.order_time <= :end
              AND o.status NOT IN ('cancelled', 'voided')
              AND o.is_deleted = false
              {store_filter}
            GROUP BY o.order_type
        """),
                params,
            )
        )
        .mappings()
        .all()
    )
    channel_breakdown = {r["channel"]: int(r["amount_fen"] or 0) for r in channel_rows}

    # 新增会员数
    new_members: int = (
        await session.execute(
            text("""
            SELECT COUNT(*) FROM customers
            WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
              AND created_at >= :start
              AND created_at <= :end
              AND is_deleted = false
        """),
            {"start": day_start, "end": day_end},
        )
    ).scalar() or 0

    return {
        "report_date": d.isoformat(),
        "store_id": store_id or "all",
        "order_count": order_count,
        "revenue_fen": revenue_fen,
        "avg_ticket_fen": avg_ticket_fen,
        "new_members": new_members,
        "payment_breakdown": payment_breakdown,
        "channel_breakdown": channel_breakdown,
    }


# ─── 端点 ───


@router.get("")
async def list_daily_reports(
    store_id: Optional[str] = Query(None, description="门店ID"),
    start_date: Optional[date] = Query(None, description="开始日期"),
    end_date: Optional[date] = Query(None, description="结束日期"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    """日报列表（支持日期范围筛选）"""
    end = end_date or date.today()
    start = start_date or (end - timedelta(days=6))
    if start > end:
        raise HTTPException(status_code=400, detail="start_date 不能晚于 end_date")

    # 构建日期列表（支持分页）
    all_dates = []
    d = start
    while d <= end:
        all_dates.append(d)
        d += timedelta(days=1)

    total = len(all_dates)
    page_dates = all_dates[(page - 1) * size : page * size]

    try:
        async with async_session_factory() as session:
            await _set_tenant(session, x_tenant_id)

            items = []
            for d in page_dates:
                report = await _query_daily_report(session, d, store_id)
                items.append(report)

        log.info(
            "daily_reports.list", tenant=x_tenant_id, store_id=store_id, start=str(start), end=str(end), total=total
        )
        return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}

    except SQLAlchemyError as exc:
        log.warning("daily_reports.list.db_error", tenant=x_tenant_id, error=str(exc))
        return {"ok": True, "data": {"items": [], "total": 0, "page": page, "size": size, "_error": "db_unavailable"}}


@router.get("/summary")
async def daily_reports_summary(
    store_id: Optional[str] = Query(None, description="门店ID"),
    start_date: Optional[date] = Query(None, description="开始日期"),
    end_date: Optional[date] = Query(None, description="结束日期"),
    dimension: str = Query("week", description="汇总维度: week / month"),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    """多日汇总（周/月维度），直接从 orders 聚合"""
    end = end_date or date.today()
    if dimension == "month":
        start = start_date or end.replace(day=1)
    else:
        start = start_date or (end - timedelta(days=6))

    day_start, _ = _day_window_utc(start)
    _, day_end = _day_window_utc(end)
    days = (end - start).days + 1

    store_filter = "AND o.store_id = :store_id::uuid" if store_id else ""
    params: dict = {"start": day_start, "end": day_end}
    if store_id:
        params["store_id"] = store_id

    try:
        async with async_session_factory() as session:
            await _set_tenant(session, x_tenant_id)

            row = (
                (
                    await session.execute(
                        text(f"""
                    SELECT
                        COUNT(*)                              AS total_orders,
                        COALESCE(SUM(o.final_amount_fen), 0) AS total_revenue_fen
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

            total_orders: int = row["total_orders"] or 0
            total_revenue: int = row["total_revenue_fen"] or 0

            new_members_total: int = (
                await session.execute(
                    text("""
                    SELECT COUNT(*) FROM customers
                    WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                      AND created_at >= :start
                      AND created_at <= :end
                      AND is_deleted = false
                """),
                    {"start": day_start, "end": day_end},
                )
            ).scalar() or 0

        log.info("daily_reports.summary", tenant=x_tenant_id, dimension=dimension, start=str(start), end=str(end))
        return {
            "ok": True,
            "data": {
                "dimension": dimension,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "days": days,
                "total_order_count": total_orders,
                "total_revenue_fen": total_revenue,
                "avg_daily_revenue_fen": total_revenue // days if days else 0,
                "avg_ticket_fen": total_revenue // total_orders if total_orders else 0,
                "total_new_members": new_members_total,
            },
        }

    except SQLAlchemyError as exc:
        log.warning("daily_reports.summary.db_error", tenant=x_tenant_id, error=str(exc))
        return {
            "ok": True,
            "data": {
                "dimension": dimension,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "days": days,
                "total_order_count": 0,
                "total_revenue_fen": 0,
                "avg_daily_revenue_fen": 0,
                "avg_ticket_fen": 0,
                "total_new_members": 0,
                "_error": "db_unavailable",
            },
        }


@router.get("/{report_date}")
async def get_daily_report(
    report_date: date,
    store_id: Optional[str] = Query(None, description="门店ID"),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    """单日经营日报详情"""
    if report_date > date.today():
        raise HTTPException(status_code=400, detail="不能查询未来日期的日报")

    try:
        async with async_session_factory() as session:
            await _set_tenant(session, x_tenant_id)
            data = await _query_daily_report(session, report_date, store_id)

        log.info("daily_reports.get", tenant=x_tenant_id, date=str(report_date), store_id=store_id)
        return {"ok": True, "data": data}

    except SQLAlchemyError as exc:
        log.warning("daily_reports.get.db_error", tenant=x_tenant_id, date=str(report_date), error=str(exc))
        return {
            "ok": True,
            "data": {
                "report_date": report_date.isoformat(),
                "store_id": store_id or "all",
                "order_count": 0,
                "revenue_fen": 0,
                "avg_ticket_fen": 0,
                "new_members": 0,
                "payment_breakdown": {},
                "channel_breakdown": {},
                "_error": "db_unavailable",
            },
        }


@router.post("/generate")
async def generate_daily_report(
    report_date: Optional[date] = Query(None, description="生成日期，默认昨天"),
    store_id: Optional[str] = Query(None, description="门店ID，默认全部"),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    """手动触发日报生成（当前为即时聚合模式，无需预计算队列）"""
    target_date = report_date or (date.today() - timedelta(days=1))
    if target_date > date.today():
        raise HTTPException(status_code=400, detail="不能生成未来日期的日报")

    log.info("daily_reports.generate", tenant=x_tenant_id, date=str(target_date), store_id=store_id)
    return {
        "ok": True,
        "data": {
            "message": f"日报数据已实时聚合: {target_date.isoformat()}",
            "report_date": target_date.isoformat(),
            "store_id": store_id or "all",
            "status": "completed",
            "note": "当前为即时聚合模式，可直接通过 GET /{date} 查询",
        },
    }
