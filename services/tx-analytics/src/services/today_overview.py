"""今日营业总览 — 经营驾驶舱核心数据源

提供单店今日概览 + 多店概览（总部视角）。
金额单位：分(fen)，前端展示时 /100 转元。
"""
from datetime import datetime, timedelta
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .sql_queries import (
    query_daily_revenue,
    query_hourly_distribution,
)

log = structlog.get_logger()


# ─── 门店健康评分 ───

async def calculate_health_score(
    store_id: str,
    tenant_id: str,
    target_date,
    db: AsyncSession,
) -> float:
    """门店健康评分（0-100）

    维度权重：
    - 营业额达成率（目标完成度）×30分
    - 翻台率                     ×20分
    - 顾客满意度（投诉率反向）    ×20分
    - 食材损耗率（反向）          ×15分
    - 员工出勤率                  ×15分

    Returns:
        float: 0-100 健康分，DB不可用时返回 50.0（基准分）
    """
    if db is None:
        return 50.0

    score = 0.0

    try:
        # ── 1. 营业额达成率 ×30分 ──
        row = await db.execute(
            text("""
                SELECT
                    COALESCE(SUM(o.final_amount_fen), 0) AS actual_fen,
                    COALESCE(s.revenue_target_fen, 0)    AS target_fen
                FROM orders o
                JOIN stores s ON s.id = o.store_id AND s.tenant_id = o.tenant_id
                WHERE o.store_id   = :store_id
                  AND o.tenant_id  = :tenant_id
                  AND COALESCE(o.biz_date, DATE(o.created_at)) = :target_date
                  AND o.status     = 'paid'
                  AND o.is_deleted = FALSE
            """),
            {"store_id": store_id, "tenant_id": tenant_id, "target_date": target_date},
        )
        rev_row = row.mappings().first()
        if rev_row and rev_row["target_fen"] and rev_row["target_fen"] > 0:
            achievement = min(rev_row["actual_fen"] / rev_row["target_fen"], 1.2)
            score += min(achievement, 1.0) * 30
        else:
            score += 15  # 目标未设置时给基准15分

        # ── 2. 翻台率 ×20分 ──
        row = await db.execute(
            text("""
                SELECT
                    COUNT(DISTINCT ts.table_id)                     AS used_tables,
                    COUNT(ts.id)                                     AS session_count,
                    COALESCE(MAX(s.table_count), 1)                  AS total_tables
                FROM table_sessions ts
                JOIN stores s ON s.id = :store_id AND s.tenant_id = :tenant_id
                WHERE ts.store_id   = :store_id
                  AND ts.tenant_id  = :tenant_id
                  AND DATE(ts.started_at) = :target_date
                  AND ts.is_deleted = FALSE
            """),
            {"store_id": store_id, "tenant_id": tenant_id, "target_date": target_date},
        )
        table_row = row.mappings().first()
        if table_row and table_row["total_tables"] > 0:
            # 目标翻台率按3次/天计算满分
            turnover = table_row["session_count"] / table_row["total_tables"]
            score += min(turnover / 3.0, 1.0) * 20
        else:
            score += 10  # 基准10分

        # ── 3. 顾客满意度（投诉率反向）×20分 ──
        row = await db.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE o.status IN ('refunded', 'cancelled')) AS complaint_count,
                    COUNT(*) AS total_count
                FROM orders o
                WHERE o.store_id   = :store_id
                  AND o.tenant_id  = :tenant_id
                  AND COALESCE(o.biz_date, DATE(o.created_at)) = :target_date
                  AND o.is_deleted = FALSE
            """),
            {"store_id": store_id, "tenant_id": tenant_id, "target_date": target_date},
        )
        sat_row = row.mappings().first()
        if sat_row and sat_row["total_count"] > 0:
            complaint_rate = sat_row["complaint_count"] / sat_row["total_count"]
            # 投诉率每超1%扣2分，上限10%扣满
            score += max(0.0, 1.0 - complaint_rate * 10) * 20
        else:
            score += 16  # 基准16分（无数据时偏高）

        # ── 4. 食材损耗率（反向）×15分 ──
        row = await db.execute(
            text("""
                SELECT
                    COALESCE(SUM(w.waste_cost_fen), 0) AS waste_fen,
                    COALESCE(SUM(p.amount_fen), 0)     AS purchase_fen
                FROM (
                    SELECT wi.store_id, wi.tenant_id,
                           SUM(wi.quantity * wi.unit_cost_fen) AS waste_cost_fen
                    FROM waste_records wi
                    WHERE wi.store_id   = :store_id
                      AND wi.tenant_id  = :tenant_id
                      AND DATE(wi.wasted_at) = :target_date
                      AND wi.is_deleted = FALSE
                    GROUP BY wi.store_id, wi.tenant_id
                ) w,
                (
                    SELECT pi.store_id, pi.tenant_id,
                           SUM(pi.total_amount_fen) AS amount_fen
                    FROM purchase_orders pi
                    WHERE pi.store_id   = :store_id
                      AND pi.tenant_id  = :tenant_id
                      AND DATE(pi.received_at) = :target_date
                      AND pi.is_deleted = FALSE
                    GROUP BY pi.store_id, pi.tenant_id
                ) p
            """),
            {"store_id": store_id, "tenant_id": tenant_id, "target_date": target_date},
        )
        waste_row = row.mappings().first()
        if waste_row and waste_row["purchase_fen"] and waste_row["purchase_fen"] > 0:
            waste_rate = waste_row["waste_fen"] / waste_row["purchase_fen"]
            # 损耗率低于3%满分，超过10%得0分
            score += max(0.0, 1.0 - max(0.0, waste_rate - 0.03) / 0.07) * 15
        else:
            score += 10  # 基准10分

        # ── 5. 员工出勤率 ×15分 ──
        row = await db.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE a.status = 'present') AS present_count,
                    COUNT(*)                                       AS scheduled_count
                FROM attendance_records a
                WHERE a.store_id   = :store_id
                  AND a.tenant_id  = :tenant_id
                  AND DATE(a.scheduled_date) = :target_date
                  AND a.is_deleted = FALSE
            """),
            {"store_id": store_id, "tenant_id": tenant_id, "target_date": target_date},
        )
        att_row = row.mappings().first()
        if att_row and att_row["scheduled_count"] > 0:
            attendance_rate = att_row["present_count"] / att_row["scheduled_count"]
            score += attendance_rate * 15
        else:
            score += 12  # 基准12分

    except Exception as exc:  # 最外层兜底：保持驾驶舱可用
        log.warning(
            "calculate_health_score.error",
            store_id=store_id,
            tenant_id=tenant_id,
            date=str(target_date),
            exc_info=True,
        )
        _ = exc  # suppress unused variable warning
        return 50.0

    return round(min(max(score, 0.0), 100.0), 1)


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

    health = await calculate_health_score(store_id, tenant_id, date, db)

    return {
        "revenue_fen": revenue_data["revenue_fen"],
        "order_count": revenue_data["order_count"],
        "table_turnover_rate": table_data["turnover_rate"],
        "health_score": health,
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
