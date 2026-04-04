"""服务员绩效统计 API 路由

W6 服务员绩效实时看板后端接口

数据来源：crew_shift_summaries 表（v151 迁移，含 crew_id/table_count/revenue_fen/turnover_rate 等字段）
"""
import uuid as _uuid
from datetime import date, timedelta
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/crew/stats", tags=["crew-stats"])


# ---------- 工具函数 ----------

def _badge(rank: int) -> Optional[str]:
    return {1: "gold", 2: "silver", 3: "bronze"}.get(rank)


def _period_to_date_range(period: str) -> tuple[date, date]:
    """将 period 字符串转换为 (start_date, end_date)。"""
    today = date.today()
    if period == "shift":
        return today, today
    if period == "today":
        return today, today
    if period == "week":
        return today - timedelta(days=6), today
    if period == "month":
        return today - timedelta(days=29), today
    return today, today


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text(f"SET LOCAL app.tenant_id = '{tenant_id}'"))


# ---------- 路由 ----------

@router.get("/me")
async def get_my_stats(
    store_id: str = Query(..., description="门店 ID"),
    period: Literal["shift", "today", "week", "month"] = Query("today"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取当前服务员的绩效数据。

    从 crew_shift_summaries 表聚合指定周期内的绩效数据。
    若 DB 表不存在或查询失败，返回空结果+日志，不抛错。
    """
    log = logger.bind(operator_id=x_operator_id, store_id=store_id, period=period)
    start_date, end_date = _period_to_date_range(period)

    try:
        await _set_rls(db, x_tenant_id)

        sql = text("""
            SELECT
                css.crew_id::text                       AS crew_id,
                COALESCE(SUM(css.table_count), 0)       AS table_count,
                COALESCE(SUM(css.revenue_fen), 0)       AS revenue_fen,
                COALESCE(SUM(css.complaint_count), 0)   AS complaint_count,
                COALESCE(SUM(css.pending_count), 0)     AS pending_count,
                COUNT(css.id)                           AS shift_days,
                COALESCE(AVG(css.turnover_rate), 0)     AS avg_turnover_rate
            FROM crew_shift_summaries css
            WHERE css.store_id = :store_id::uuid
              AND css.crew_id = :crew_id::uuid
              AND css.shift_date BETWEEN :start_date AND :end_date
              AND css.is_deleted = false
            GROUP BY css.crew_id
        """)
        result = await db.execute(sql, {
            "store_id": store_id,
            "crew_id": x_operator_id,
            "start_date": start_date,
            "end_date": end_date,
        })
        row = result.fetchone()

        if not row:
            # 无数据时返回空绩效
            stats = {
                "operator_id": x_operator_id,
                "operator_name": None,
                "table_count": 0,
                "table_turns": 0,
                "revenue_contributed": 0,
                "avg_check": 0,
                "upsell_count": 0,
                "upsell_rate": 0.0,
                "complaint_count": 0,
                "rank": None,
                "total_staff": 0,
                "period": period,
            }
            log.info("crew_stats_me_no_data")
            return {"ok": True, "data": stats}

        revenue = int(row.revenue_fen)
        table_count = int(row.table_count)
        stats = {
            "operator_id": x_operator_id,
            "operator_name": None,              # crew_shift_summaries 无 name 字段，需联查 employees
            "table_count": table_count,
            "table_turns": table_count,
            "revenue_contributed": revenue,
            "avg_check": revenue // max(table_count, 1),
            "upsell_count": 0,                  # crew_shift_summaries 暂无 upsell 字段
            "upsell_rate": 0.0,
            "complaint_count": int(row.complaint_count),
            "rank": None,                       # 排名需在 leaderboard 端点计算
            "total_staff": 0,
            "period": period,
        }

        log.info("crew_stats_me_ok", revenue_fen=revenue, table_count=table_count)
        return {"ok": True, "data": stats}

    except SQLAlchemyError as e:
        log.warning("crew_stats_me_db_error", error=str(e))
        return {"ok": True, "data": {
            "operator_id": x_operator_id, "operator_name": None,
            "table_count": 0, "table_turns": 0, "revenue_contributed": 0,
            "avg_check": 0, "upsell_count": 0, "upsell_rate": 0.0,
            "complaint_count": 0, "rank": None, "total_staff": 0, "period": period,
        }}
    except Exception as e:  # noqa: BLE001 — MLPS3-P0: 最外层HTTP兜底
        log.error("crew_stats_me_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.get("/leaderboard")
async def get_leaderboard(
    store_id: str = Query(..., description="门店 ID"),
    period: Literal["shift", "today", "week", "month"] = Query("today"),
    metric: Literal["revenue", "turns", "upsell", "response"] = Query("revenue"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取排行榜数据，从 crew_shift_summaries 按指定维度排序。

    metric:
    - revenue: 贡献营收（revenue_fen 降序）
    - turns:   翻台次数（table_count 降序）
    - upsell:  加菜次数（暂无字段，返回空列表）
    - response: 服务铃响应速度（暂无字段，返回空列表）
    """
    log = logger.bind(store_id=store_id, period=period, metric=metric)
    start_date, end_date = _period_to_date_range(period)

    if metric in ("upsell", "response"):
        # crew_shift_summaries 暂无对应字段，graceful 返回空列表
        log.info("crew_stats_leaderboard_metric_not_supported", metric=metric)
        return {"ok": True, "data": {"items": [], "total": 0}}

    order_col = "revenue_fen" if metric == "revenue" else "table_count"

    try:
        await _set_rls(db, x_tenant_id)

        sql = text(f"""
            SELECT
                css.crew_id::text                       AS crew_id,
                COALESCE(SUM(css.{order_col}), 0)       AS metric_value,
                COALESCE(SUM(css.revenue_fen), 0)       AS revenue_fen,
                COALESCE(SUM(css.table_count), 0)       AS table_count
            FROM crew_shift_summaries css
            WHERE css.store_id = :store_id::uuid
              AND css.shift_date BETWEEN :start_date AND :end_date
              AND css.is_deleted = false
            GROUP BY css.crew_id
            ORDER BY metric_value DESC
            LIMIT 50
        """)
        result = await db.execute(sql, {
            "store_id": store_id,
            "start_date": start_date,
            "end_date": end_date,
        })
        rows = result.fetchall()

        items = []
        for i, row in enumerate(rows):
            rank = i + 1
            items.append({
                "rank": rank,
                "operator_id": row.crew_id,
                "operator_name": None,          # 需联查 employees 表
                "value": int(row.metric_value),
                "badge": _badge(rank),
            })

        log.info("crew_stats_leaderboard_ok", count=len(items))
        return {"ok": True, "data": {"items": items, "total": len(items)}}

    except SQLAlchemyError as e:
        log.warning("crew_stats_leaderboard_db_error", error=str(e))
        return {"ok": True, "data": {"items": [], "total": 0}}
    except Exception as e:  # noqa: BLE001 — MLPS3-P0: 最外层HTTP兜底
        log.error("crew_stats_leaderboard_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.get("/trend")
async def get_trend(
    operator_id: str = Query(..., description="操作员 ID（crew_id UUID）"),
    store_id: str = Query(..., description="门店 ID"),
    days: Literal[7, 30] = Query(7, description="近N天"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取指定服务员近 N 天每日绩效趋势数据。

    从 crew_shift_summaries 按 shift_date 逐日聚合。
    若某天无数据则补零行，确保返回连续日期序列。
    """
    log = logger.bind(operator_id=operator_id, store_id=store_id, days=days)
    today = date.today()
    start_date = today - timedelta(days=days - 1)

    try:
        await _set_rls(db, x_tenant_id)

        sql = text("""
            SELECT
                css.shift_date                          AS shift_date,
                COALESCE(SUM(css.table_count), 0)       AS table_count,
                COALESCE(SUM(css.revenue_fen), 0)       AS revenue_fen,
                COALESCE(SUM(css.complaint_count), 0)   AS complaint_count
            FROM crew_shift_summaries css
            WHERE css.store_id = :store_id::uuid
              AND css.crew_id = :crew_id::uuid
              AND css.shift_date BETWEEN :start_date AND :end_date
              AND css.is_deleted = false
            GROUP BY css.shift_date
            ORDER BY css.shift_date
        """)
        result = await db.execute(sql, {
            "store_id": store_id,
            "crew_id": operator_id,
            "start_date": start_date,
            "end_date": today,
        })
        db_rows = {row.shift_date: row for row in result.fetchall()}

        # 补零确保连续日期
        trend = []
        for d in range(days - 1, -1, -1):
            day = today - timedelta(days=d)
            row = db_rows.get(day)
            trend.append({
                "date": day.isoformat(),
                "table_turns": int(row.table_count) if row else 0,
                "revenue_contributed": int(row.revenue_fen) if row else 0,
                "upsell_count": 0,      # crew_shift_summaries 暂无 upsell 字段
            })

        log.info("crew_stats_trend_ok", data_points=len(trend))
        return {"ok": True, "data": {"items": trend, "operator_id": operator_id}}

    except SQLAlchemyError as e:
        log.warning("crew_stats_trend_db_error", error=str(e))
        # 返回全零趋势，不抛错
        trend = [
            {"date": (today - timedelta(days=d)).isoformat(),
             "table_turns": 0, "revenue_contributed": 0, "upsell_count": 0}
            for d in range(days - 1, -1, -1)
        ]
        return {"ok": True, "data": {"items": trend, "operator_id": operator_id}}
    except Exception as e:  # noqa: BLE001 — MLPS3-P0: 最外层HTTP兜底
        log.error("crew_stats_trend_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")
