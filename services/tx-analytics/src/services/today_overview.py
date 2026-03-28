"""今日营业总览 — 经营驾驶舱核心数据源

提供单店今日概览 + 多店概览（总部视角）。
金额单位：分(fen)，前端展示时 /100 转元。
"""
import structlog
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .sql_queries import (
    query_daily_revenue,
    query_hourly_distribution,
    query_alerts_today,
)

log = structlog.get_logger()


# ─── 纯函数：环比计算 ───

def calc_pct_change(current: int, previous: int) -> Optional[float]:
    """计算百分比变化，previous 为 0 时返回 None"""
    if previous <= 0:
        return None
    return round((current - previous) / previous * 100, 1)


def find_peak_hour(hourly_revenue: dict[int, int]) -> Optional[int]:
    """从小时→营收(分)映射中找到峰值小时"""
    if not hourly_revenue:
        return None
    return max(hourly_revenue, key=hourly_revenue.get)


# ─── 单店今日总览 ───

async def get_today_overview(
    store_id: str,
    tenant_id: str,
    db,
) -> dict:
    """今日营业总览（单店）

    Args:
        store_id: 门店ID
        tenant_id: 租户ID
        db: 数据库连接（AsyncSession）

    Returns:
        {revenue_fen, order_count, avg_ticket_fen, table_turnover_rate,
         vs_yesterday: {revenue_pct, orders_pct},
         vs_last_week: {revenue_pct, orders_pct},
         peak_hour, current_occupancy_pct}
    """
    log.info("get_today_overview", store_id=store_id, tenant_id=tenant_id)

    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    last_week_same_day = today - timedelta(days=7)

    # --- 查询今日数据 ---
    today_data = await _query_daily_summary(db, store_id, tenant_id, today)
    yesterday_data = await _query_daily_summary(db, store_id, tenant_id, yesterday)
    last_week_data = await _query_daily_summary(db, store_id, tenant_id, last_week_same_day)

    revenue_fen = today_data["revenue_fen"]
    order_count = today_data["order_count"]
    avg_ticket_fen = revenue_fen // order_count if order_count > 0 else 0

    # 环比
    vs_yesterday = {
        "revenue_pct": calc_pct_change(revenue_fen, yesterday_data["revenue_fen"]),
        "orders_pct": calc_pct_change(order_count, yesterday_data["order_count"]),
    }
    vs_last_week = {
        "revenue_pct": calc_pct_change(revenue_fen, last_week_data["revenue_fen"]),
        "orders_pct": calc_pct_change(order_count, last_week_data["order_count"]),
    }

    # 小时分布 & 峰值
    hourly = await _query_hourly_revenue(db, store_id, tenant_id, today)
    peak_hour = find_peak_hour(hourly)

    # 实时上座率
    occupancy = await _query_current_occupancy(db, store_id, tenant_id)

    return {
        "store_id": store_id,
        "date": today.isoformat(),
        "revenue_fen": revenue_fen,
        "order_count": order_count,
        "avg_ticket_fen": avg_ticket_fen,
        "table_turnover_rate": today_data["table_turnover_rate"],
        "vs_yesterday": vs_yesterday,
        "vs_last_week": vs_last_week,
        "peak_hour": peak_hour,
        "current_occupancy_pct": occupancy,
    }


# ─── 多店概览（总部视角） ───

async def get_multi_store_overview(
    tenant_id: str,
    db,
) -> list[dict]:
    """多店概览列表

    Returns:
        [{store_id, store_name, revenue_fen, orders, health_score}]
    """
    log.info("get_multi_store_overview", tenant_id=tenant_id)

    today = datetime.now().date()
    stores = await _query_tenant_stores(db, tenant_id)

    results = []
    for store in stores:
        summary = await _query_daily_summary(db, store["store_id"], tenant_id, today)
        results.append({
            "store_id": store["store_id"],
            "store_name": store["store_name"],
            "revenue_fen": summary["revenue_fen"],
            "orders": summary["order_count"],
            "health_score": summary.get("health_score", 50.0),
        })

    # 按营收降序排列
    results.sort(key=lambda x: x["revenue_fen"], reverse=True)
    return results


# ─── 数据库查询（通过统一SQL查询层） ───

async def _query_daily_summary(db: AsyncSession, store_id: str, tenant_id: str, date) -> dict:
    """查询某日汇总数据，委托给 sql_queries 统一查询层"""
    revenue_data = await query_daily_revenue(store_id, date, tenant_id, db)

    # 翻台率需额外查询桌台会话
    from .sql_queries import query_table_sessions
    table_data = await query_table_sessions(store_id, date, tenant_id, db)

    return {
        "revenue_fen": revenue_data["revenue_fen"],
        "order_count": revenue_data["order_count"],
        "table_turnover_rate": table_data["turnover_rate"],
        "health_score": 50.0,  # TODO: 接入门店健康评分服务
    }


async def _query_hourly_revenue(db: AsyncSession, store_id: str, tenant_id: str, date) -> dict[int, int]:
    """查询小时维度营收分布，委托给 sql_queries 统一查询层"""
    hourly_data = await query_hourly_distribution(store_id, date, tenant_id, db)
    return {item["hour"]: item["revenue_fen"] for item in hourly_data}


async def _query_current_occupancy(db: AsyncSession, store_id: str, tenant_id: str) -> float:
    """查询当前上座率百分比"""
    row = await db.execute(
        text("""
            SELECT COUNT(*) FILTER (WHERE status = 'occupied') AS occupied,
                   COUNT(*) AS total
            FROM tables
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND is_deleted = FALSE
        """),
        {"store_id": store_id, "tenant_id": tenant_id},
    )
    result = row.mappings().first()
    if result is None or result["total"] == 0:
        return 0.0
    return round(result["occupied"] / result["total"] * 100, 1)


async def _query_tenant_stores(db: AsyncSession, tenant_id: str) -> list[dict]:
    """查询租户下所有门店"""
    row = await db.execute(
        text("""
            SELECT store_id, store_name
            FROM stores
            WHERE tenant_id = :tenant_id AND is_deleted = FALSE
        """),
        {"tenant_id": tenant_id},
    )
    return [dict(r) for r in row.mappings().all()]
