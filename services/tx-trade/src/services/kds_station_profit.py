"""档口毛利核算服务

天财商龙特色功能：每条生产动线的营收/毛利独立核算，档口即利润中心。

计算逻辑：
  营收  = 已出品任务关联的菜品售价 × 数量
  成本  = 菜品 BOM（bill of materials）中食材成本合计
  毛利  = 营收 - 成本
  毛利率 = 毛利 / 营收

支持时间粒度：
  - 今日
  - 本周
  - 本月
  - 自定义日期区间（start_date ~ end_date）

输出按档口分组，每档口一行汇总数据。
"""
import uuid
from datetime import date, datetime
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


async def get_station_profit_report(
    tenant_id: str,
    store_id: str,
    start_date: date,
    end_date: date,
    db: AsyncSession,
) -> list[dict]:
    """计算各档口的营收、成本、毛利数据。

    通过 SQL JOIN kds_tasks → order_items → dish_bom_items 计算。
    """
    sql = text("""
        WITH completed_tasks AS (
            SELECT
                kt.dept_id,
                kt.completed_at::DATE            AS sale_date,
                oi.dish_id,
                oi.quantity,
                oi.unit_price,
                oi.quantity * oi.unit_price      AS revenue
            FROM kds_tasks kt
            JOIN order_items oi ON oi.id = kt.order_item_id
            WHERE kt.tenant_id    = :tenant_id
              AND kt.status       = 'done'
              AND kt.completed_at::DATE BETWEEN :start_date AND :end_date
              AND kt.is_deleted   = FALSE
        ),
        bom_costs AS (
            SELECT
                dbi.dish_id,
                SUM(dbi.quantity * i.latest_cost_price) AS unit_cost
            FROM dish_bom_items dbi
            JOIN ingredients i ON i.id = dbi.ingredient_id
            WHERE dbi.tenant_id = :tenant_id
              AND dbi.is_deleted = FALSE
              AND i.is_deleted   = FALSE
            GROUP BY dbi.dish_id
        )
        SELECT
            ct.dept_id::TEXT                           AS dept_id,
            pd.name                                    AS dept_name,
            COUNT(*)                                   AS dish_count,
            SUM(ct.revenue)::NUMERIC(12,2)             AS revenue,
            SUM(ct.quantity * COALESCE(bc.unit_cost, 0))::NUMERIC(12,2) AS cost,
            (SUM(ct.revenue) - SUM(ct.quantity * COALESCE(bc.unit_cost, 0)))::NUMERIC(12,2) AS profit,
            CASE
                WHEN SUM(ct.revenue) > 0
                THEN ROUND(
                    (SUM(ct.revenue) - SUM(ct.quantity * COALESCE(bc.unit_cost, 0)))
                    / SUM(ct.revenue) * 100, 1
                )
                ELSE 0
            END::FLOAT                                 AS profit_margin_pct
        FROM completed_tasks ct
        LEFT JOIN bom_costs bc ON bc.dish_id = ct.dish_id
        LEFT JOIN production_depts pd ON pd.id = ct.dept_id
        WHERE ct.dept_id IS NOT NULL
        GROUP BY ct.dept_id, pd.name
        ORDER BY revenue DESC
    """)

    result = await db.execute(sql, {
        "tenant_id": tenant_id,
        "start_date": start_date,
        "end_date": end_date,
    })
    rows = result.mappings().all()

    report = []
    for r in rows:
        profit_margin = float(r["profit_margin_pct"] or 0)
        # 颜色语义：毛利率 ≥60% 绿色 / 40~60% 黄色 / <40% 红色
        if profit_margin >= 60:
            status = "healthy"
        elif profit_margin >= 40:
            status = "warning"
        else:
            status = "danger"

        report.append({
            "dept_id": r["dept_id"],
            "dept_name": r["dept_name"] or "未知档口",
            "dish_count": int(r["dish_count"] or 0),
            "revenue": float(r["revenue"] or 0),
            "cost": float(r["cost"] or 0),
            "profit": float(r["profit"] or 0),
            "profit_margin_pct": profit_margin,
            "status": status,
        })

    logger.info(
        "kds.station_profit.computed",
        store_id=store_id,
        start=start_date.isoformat(),
        end=end_date.isoformat(),
        depts=len(report),
    )
    return report


async def get_station_profit_summary(
    tenant_id: str,
    store_id: str,
    start_date: date,
    end_date: date,
    db: AsyncSession,
) -> dict:
    """全店汇总：总营收、总毛利、平均毛利率。"""
    detail = await get_station_profit_report(tenant_id, store_id, start_date, end_date, db)
    if not detail:
        return {"total_revenue": 0, "total_profit": 0, "avg_margin_pct": 0, "depts": []}

    total_revenue = sum(d["revenue"] for d in detail)
    total_profit = sum(d["profit"] for d in detail)
    avg_margin = total_profit / total_revenue * 100 if total_revenue > 0 else 0

    return {
        "total_revenue": round(total_revenue, 2),
        "total_profit": round(total_profit, 2),
        "avg_margin_pct": round(avg_margin, 1),
        "depts": detail,
    }
