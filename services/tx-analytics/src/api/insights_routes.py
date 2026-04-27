"""经营洞察 API 路由 — 门店对比排名 + 餐段分析

前缀: /api/v1/analytics

端点:
  GET  /store-insights    — 多门店经营排名（营收/客流/翻台率/毛利率/健康度）
  GET  /period-analysis   — 餐段分析（按午/晚/夜宵分时段营收/客流/热销菜品）
"""

import uuid
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/analytics", tags=["insights"])


# ─── 辅助 ──────────────────────────────────────────────────────────────────────


def _require_tenant(tenant_id: Optional[str]) -> uuid.UUID:
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    try:
        return uuid.UUID(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid tenant_id: {tenant_id}") from exc


def _today() -> str:
    return date.today().isoformat()


def _date_range(period: str) -> tuple[str, str]:
    """根据 period 返回 (date_from, date_to) 字符串"""
    today = date.today()
    if period == "week":
        date_from = (today - timedelta(days=6)).isoformat()
    elif period == "month":
        date_from = (today - timedelta(days=29)).isoformat()
    else:  # today
        date_from = today.isoformat()
    return date_from, today.isoformat()


def _prev_date_range(period: str) -> tuple[str, str]:
    """返回上一个等长周期的 (date_from, date_to)"""
    today = date.today()
    if period == "week":
        days = 7
    elif period == "month":
        days = 30
    else:
        days = 1
    date_to = (today - timedelta(days=days)).isoformat()
    date_from = (today - timedelta(days=days * 2 - 1)).isoformat()
    return date_from, date_to


# ═══════════════════════════════════════════════════════════════════════════════
# 门店经营洞察
# ═══════════════════════════════════════════════════════════════════════════════


class StoreMetric(BaseModel):
    store_id: str
    store_name: str
    region: str
    revenue_fen: int
    order_count: int
    guest_count: int
    avg_check_fen: int
    table_turn_rate: float
    gross_margin: float
    health_score: int
    revenue_growth: float
    complaint_count: int


class StoreInsightsResponse(BaseModel):
    ok: bool = True
    data: dict = Field(default_factory=dict)


@router.get("/store-insights")
async def get_store_insights(
    period: str = Query("today", description="today|week|month"),
    region: str = Query("", description="区域筛选（空=全部）"),
    x_tenant_id: str = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """多门店经营排名 — 供 StoreInsightsPage 调用"""
    tid = _require_tenant(x_tenant_id)
    date_from, date_to = _date_range(period)

    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tid)},
    )

    items: list[dict] = []

    try:
        # ── 主查询：从 mv_store_pnl 聚合 ──────────────────────────────────────
        pnl_sql = text("""
            SELECT
                p.store_id::text,
                s.store_name,
                COALESCE(s.city, '未知') AS region,
                SUM(p.gross_revenue_fen)::bigint AS revenue_fen,
                SUM(p.order_count)::bigint AS order_count,
                SUM(p.customer_count)::bigint AS guest_count,
                CASE WHEN SUM(p.order_count) > 0
                     THEN SUM(p.gross_revenue_fen) / SUM(p.order_count)
                     ELSE 0 END::bigint AS avg_check_fen,
                CASE WHEN SUM(p.gross_revenue_fen) > 0
                     THEN SUM(p.gross_profit_fen)::float / SUM(p.gross_revenue_fen)
                     ELSE 0 END AS gross_margin
            FROM mv_store_pnl p
            JOIN stores s ON s.id = p.store_id AND s.tenant_id = p.tenant_id
            WHERE p.tenant_id = :tid::uuid
              AND p.stat_date BETWEEN :date_from AND :date_to
              AND COALESCE(s.is_deleted, false) = false
            GROUP BY p.store_id, s.store_name, s.city
            ORDER BY SUM(p.gross_revenue_fen) DESC
        """)
        result = await db.execute(pnl_sql, {"tid": str(tid), "date_from": date_from, "date_to": date_to})
        rows = result.mappings().all()

        if not rows:
            # ── Fallback：mv_store_pnl 尚无数据，直接从 orders 聚合 ──────────
            fallback_sql = text("""
                SELECT
                    store_id::text,
                    store_id::text AS store_name,
                    '未知' AS region,
                    COALESCE(SUM(final_amount_fen), 0)::bigint AS revenue_fen,
                    COUNT(*)::bigint AS order_count,
                    0::bigint AS guest_count,
                    CASE WHEN COUNT(*) > 0
                         THEN COALESCE(SUM(final_amount_fen), 0) / COUNT(*)
                         ELSE 0 END::bigint AS avg_check_fen,
                    0.0::float AS gross_margin
                FROM orders
                WHERE tenant_id = :tid::uuid
                  AND status = 'paid'
                  AND DATE(created_at AT TIME ZONE 'Asia/Shanghai') BETWEEN :date_from AND :date_to
                GROUP BY store_id
                ORDER BY revenue_fen DESC
            """)
            fallback_result = await db.execute(
                fallback_sql, {"tid": str(tid), "date_from": date_from, "date_to": date_to}
            )
            rows = fallback_result.mappings().all()

        if not rows:
            return {"ok": True, "data": {"items": [], "period": period, "total": 0}}

        store_ids = [r["store_id"] for r in rows]

        # ── 翻台率：tables 数量 + 订单数推算 ─────────────────────────────────
        table_count_sql = text("""
            SELECT store_id::text, COUNT(*) AS cnt
            FROM tables
            WHERE tenant_id = :tid::uuid
              AND store_id = ANY(:store_ids::uuid[])
            GROUP BY store_id
        """)
        table_result = await db.execute(table_count_sql, {"tid": str(tid), "store_ids": store_ids})
        table_counts: dict[str, int] = {str(r["store_id"]): int(r["cnt"]) for r in table_result.mappings().all()}

        # ── 上一周期营收（用于计算 revenue_growth）────────────────────────────
        prev_from, prev_to = _prev_date_range(period)
        prev_sql = text("""
            SELECT store_id::text, SUM(gross_revenue_fen)::bigint AS revenue_fen
            FROM mv_store_pnl
            WHERE tenant_id = :tid::uuid
              AND stat_date BETWEEN :date_from AND :date_to
            GROUP BY store_id
        """)
        prev_result = await db.execute(prev_sql, {"tid": str(tid), "date_from": prev_from, "date_to": prev_to})
        prev_revenue: dict[str, int] = {str(r["store_id"]): int(r["revenue_fen"]) for r in prev_result.mappings().all()}

        # ── 合规告警（open）────────────────────────────────────────────────────
        alert_sql = text("""
            SELECT store_id::text, COUNT(*) AS cnt
            FROM compliance_alerts
            WHERE tenant_id = :tid::uuid
              AND store_id = ANY(:store_ids::uuid[])
              AND status = 'open'
              AND created_at >= :date_from::date
            GROUP BY store_id
        """)
        alert_result = await db.execute(alert_sql, {"tid": str(tid), "store_ids": store_ids, "date_from": date_from})
        alert_counts: dict[str, int] = {str(r["store_id"]): int(r["cnt"]) for r in alert_result.mappings().all()}

        # ── 组装返回数据 ───────────────────────────────────────────────────────
        # period 天数（用于翻台率分母）
        days = {"today": 1, "week": 7, "month": 30}.get(period, 1)

        for r in rows:
            sid = r["store_id"]
            order_count = int(r["order_count"])
            tbl_cnt = table_counts.get(sid, 0)
            # 翻台率 ≈ 订单数 / (桌台数 * 天数)，桌台数为 0 时 fallback 0
            turn_rate = round(order_count / (tbl_cnt * days), 2) if tbl_cnt > 0 else 0.0

            open_alerts = alert_counts.get(sid, 0)
            health = max(0, 100 - open_alerts * 5)

            cur_rev = int(r["revenue_fen"])
            prev_rev = prev_revenue.get(sid, 0)
            growth = round((cur_rev - prev_rev) / prev_rev, 4) if prev_rev > 0 else 0.0

            items.append(
                {
                    "store_id": sid,
                    "store_name": r["store_name"],
                    "region": r["region"],
                    "revenue_fen": cur_rev,
                    "order_count": order_count,
                    "guest_count": int(r["guest_count"]),
                    "avg_check_fen": int(r["avg_check_fen"]),
                    "table_turn_rate": turn_rate,
                    "gross_margin": round(float(r["gross_margin"]), 4),
                    "health_score": health,
                    "revenue_growth": growth,
                    "complaint_count": open_alerts,
                }
            )

    except SQLAlchemyError:
        items = []

    # region 过滤在 Python 层做（mv_store_pnl 不含 region 字段）
    if region:
        items = [s for s in items if s["region"] == region]

    return {
        "ok": True,
        "data": {
            "items": items,
            "period": period,
            "total": len(items),
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 餐段分析
# ═══════════════════════════════════════════════════════════════════════════════


class TopDish(BaseModel):
    name: str
    count: int
    revenue_fen: int


class PeriodData(BaseModel):
    period_name: str
    start_time: str
    end_time: str
    revenue_fen: int
    order_count: int
    guest_count: int
    avg_check_fen: int
    table_turn_rate: float
    top_dishes: list[TopDish]
    peak_hour: str
    occupancy_rate: float


# 餐段定义：name → (start_time展示, end_time展示, hour_start_inclusive, hour_end_exclusive)
# SQL 使用 EXTRACT(HOUR) 取整小时；边界按前闭后开处理
_PERIODS = [
    ("早茶", "07:00", "10:30", 7, 10),
    ("午餐", "10:30", "14:00", 10, 14),
    ("下午茶", "14:00", "17:00", 14, 17),
    ("晚餐", "17:00", "21:00", 17, 21),
    ("夜宵", "21:00", "23:59", 21, 24),
]

_PERIOD_META: dict[str, tuple[str, str]] = {name: (start, end) for name, start, end, _, _ in _PERIODS}


def _hour_case_sql() -> str:
    """生成 CASE WHEN … 把小时映射为餐段名称的 SQL 片段"""
    branches = []
    for name, _, _, h_start, h_end in _PERIODS:
        if h_end == 24:
            branches.append(
                f"WHEN EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Shanghai') >= {h_start} THEN '{name}'"
            )
        else:
            branches.append(
                f"WHEN EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Shanghai') >= {h_start} "
                f"AND EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Shanghai') < {h_end} THEN '{name}'"
            )
    return "CASE\n        " + "\n        ".join(branches) + "\n        ELSE NULL END"


@router.get("/period-analysis")
async def get_period_analysis(
    store_id: str = Query(..., description="门店ID"),
    analysis_date: str = Query("", description="日期 YYYY-MM-DD（默认今日）"),
    x_tenant_id: str = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """按餐段分析 — 供 PeriodAnalysisPage 调用"""
    tid = _require_tenant(x_tenant_id)
    target_date = analysis_date or _today()

    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tid)},
    )

    periods_out: list[dict] = []

    try:
        # ── 桌台数（用于翻台率分母）──────────────────────────────────────────
        tbl_sql = text("""
            SELECT COUNT(*) AS cnt
            FROM tables
            WHERE tenant_id = :tid::uuid AND store_id = :store_id::uuid
        """)
        tbl_result = await db.execute(tbl_sql, {"tid": str(tid), "store_id": store_id})
        tbl_row = tbl_result.mappings().first()
        table_count: int = int(tbl_row["cnt"]) if tbl_row else 0

        # ── 主聚合：按餐段汇总订单 ────────────────────────────────────────────
        period_sql = text(f"""
            SELECT
                {_hour_case_sql()} AS period_name,
                COUNT(*)::int AS order_count,
                COALESCE(SUM(final_amount_fen), 0)::bigint AS revenue_fen,
                COALESCE(SUM(guest_count), 0)::int AS guest_count
            FROM orders
            WHERE tenant_id = :tid::uuid
              AND store_id = :store_id::uuid
              AND status = 'paid'
              AND DATE(created_at AT TIME ZONE 'Asia/Shanghai') = :target_date
            GROUP BY period_name
            HAVING {_hour_case_sql()} IS NOT NULL
            ORDER BY MIN(created_at)
        """)
        period_result = await db.execute(
            period_sql, {"tid": str(tid), "store_id": store_id, "target_date": target_date}
        )
        period_rows = {r["period_name"]: r for r in period_result.mappings().all()}

        if not period_rows:
            return {"ok": True, "data": {"periods": [], "store_id": store_id, "date": target_date}}

        # ── peak_hour：每个餐段内按半小时分桶找订单最多的时段 ─────────────────
        peak_sql = text(f"""
            SELECT
                {_hour_case_sql()} AS period_name,
                TO_CHAR(
                    DATE_TRUNC('hour', created_at AT TIME ZONE 'Asia/Shanghai') +
                    INTERVAL '30 min' * FLOOR(
                        EXTRACT(MINUTE FROM created_at AT TIME ZONE 'Asia/Shanghai') / 30
                    ),
                    'HH24:MI'
                ) AS bucket_start,
                COUNT(*) AS cnt
            FROM orders
            WHERE tenant_id = :tid::uuid
              AND store_id = :store_id::uuid
              AND status = 'paid'
              AND DATE(created_at AT TIME ZONE 'Asia/Shanghai') = :target_date
            GROUP BY period_name, bucket_start
            HAVING {_hour_case_sql()} IS NOT NULL
            ORDER BY period_name, cnt DESC
        """)
        peak_result = await db.execute(peak_sql, {"tid": str(tid), "store_id": store_id, "target_date": target_date})
        # 每个餐段取 cnt 最大的那个半小时
        peak_hours: dict[str, str] = {}
        for pr in peak_result.mappings().all():
            pname = pr["period_name"]
            if pname not in peak_hours:
                # 第一行即最大（ORDER BY cnt DESC）
                bucket = pr["bucket_start"]
                # 计算结束（+30min）
                h, m = map(int, bucket.split(":"))
                end_m = (m + 30) % 60
                end_h = h + (1 if m + 30 >= 60 else 0)
                peak_hours[pname] = f"{bucket}-{end_h:02d}:{end_m:02d}"

        # ── 热销菜：一次性查所有餐段，Python 侧分组 ───────────────────────────
        dish_sql = text(f"""
            SELECT
                {_hour_case_sql().replace("created_at", "o.created_at")} AS period_name,
                oi.dish_name,
                SUM(oi.quantity)::int AS total_qty,
                SUM(oi.total_price_fen)::bigint AS revenue_fen
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
            WHERE oi.tenant_id = :tid::uuid
              AND o.store_id = :store_id::uuid
              AND o.status = 'paid'
              AND DATE(o.created_at AT TIME ZONE 'Asia/Shanghai') = :target_date
            GROUP BY period_name, oi.dish_name
            HAVING {_hour_case_sql().replace("created_at", "o.created_at")} IS NOT NULL
            ORDER BY period_name, total_qty DESC
        """)
        dish_result = await db.execute(dish_sql, {"tid": str(tid), "store_id": store_id, "target_date": target_date})
        # 按餐段分组，每段取前5
        dishes_by_period: dict[str, list[dict]] = {}
        for dr in dish_result.mappings().all():
            pname = dr["period_name"]
            if pname not in dishes_by_period:
                dishes_by_period[pname] = []
            if len(dishes_by_period[pname]) < 5:
                dishes_by_period[pname].append(
                    {
                        "name": dr["dish_name"],
                        "count": int(dr["total_qty"]),
                        "revenue_fen": int(dr["revenue_fen"]),
                    }
                )

        # ── 按照预定顺序输出各餐段 ────────────────────────────────────────────
        for name, start_time, end_time, _, _ in _PERIODS:
            if name not in period_rows:
                continue
            row = period_rows[name]
            order_count = int(row["order_count"])
            revenue_fen = int(row["revenue_fen"])
            guest_count = int(row["guest_count"])
            avg_check = revenue_fen // max(1, order_count)
            turn_rate = round(guest_count / table_count, 2) if table_count > 0 else 0.0

            periods_out.append(
                {
                    "period_name": name,
                    "start_time": start_time,
                    "end_time": end_time,
                    "revenue_fen": revenue_fen,
                    "order_count": order_count,
                    "guest_count": guest_count,
                    "avg_check_fen": avg_check,
                    "table_turn_rate": turn_rate,
                    "top_dishes": dishes_by_period.get(name, []),
                    "peak_hour": peak_hours.get(name, ""),
                    "occupancy_rate": 0.0,  # 需桌台实时状态，当前无法计算
                }
            )

    except SQLAlchemyError:
        periods_out = []

    return {
        "ok": True,
        "data": {
            "periods": periods_out,
            "store_id": store_id,
            "date": target_date,
        },
    }
