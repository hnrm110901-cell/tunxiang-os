"""
费控看板 API 路由

5 个端点，提供费控全局数据汇总和分析视图：
  GET /overview        — 费控总览（本月支出/预算执行率/待审批/发票状态）
  GET /by-store        — 按门店维度汇总（支持多门店对比）
  GET /by-category     — 按科目维度汇总（科目占比/趋势）
  GET /trend           — 费用趋势（月度环比/同比）
  GET /top-applicants  — 高频申请人排行（按金额/次数）

金额约定：所有金额字段单位为分(fen)，1 元 = 100 分，展示层负责转换。
所有查询显式传入 tenant_id，确保 RLS 安全隔离。
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timezone
from typing import List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter()
log = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 依赖注入
# ─────────────────────────────────────────────────────────────────────────────

async def get_tenant_id(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> UUID:
    try:
        return UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的租户ID格式")


async def get_current_user(x_user_id: str = Header(..., alias="X-User-ID")) -> UUID:
    try:
        return UUID(x_user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的用户ID格式")


# ─────────────────────────────────────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────────────────────────────────────

def _ok(data: object) -> dict:
    return {"ok": True, "data": data, "error": None}


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    """返回 (month_start, month_end)。"""
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    return first, last


def _current_ym() -> tuple[int, int]:
    today = date.today()
    return today.year, today.month


def _quarter_bounds(year: int, month: int) -> tuple[date, date]:
    """返回该月所在季度的起止日期。"""
    quarter = (month - 1) // 3
    q_start_month = quarter * 3 + 1
    q_end_month = q_start_month + 2
    start = date(year, q_start_month, 1)
    end = date(year, q_end_month, calendar.monthrange(year, q_end_month)[1])
    return start, end


# ─────────────────────────────────────────────────────────────────────────────
# GET /overview — 费控总览
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/overview",
    summary="费控总览",
    description="返回本月/本季度费用汇总、预算执行率、待审批单据、发票核验状态及环比增长。",
)
async def get_overview(
    year: Optional[int] = Query(None, ge=2020, le=2030),
    month: Optional[int] = Query(None, ge=1, le=12),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    _year, _month = _current_ym()
    year = year or _year
    month = month or _month

    m_start, m_end = _month_bounds(year, month)
    q_start, q_end = _quarter_bounds(year, month)

    # 上月范围（用于环比）
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    pm_start, pm_end = _month_bounds(prev_year, prev_month)

    try:
        # 1) 本月费用汇总（已审批+已付款）
        r = await db.execute(text("""
            SELECT
                COALESCE(SUM(total_amount), 0)                          AS month_total_fen,
                COUNT(*)                                                AS month_count,
                COALESCE(SUM(CASE WHEN status='paid' THEN total_amount ELSE 0 END), 0)
                                                                        AS month_paid_fen
            FROM expense_applications
            WHERE tenant_id = :tid
              AND is_deleted = false
              AND status IN ('approved', 'paid')
              AND created_at::date BETWEEN :s AND :e
        """), {"tid": str(tenant_id), "s": m_start, "e": m_end})
        row = r.mappings().one()
        month_total_fen = int(row["month_total_fen"])
        month_count = int(row["month_count"])
        month_paid_fen = int(row["month_paid_fen"])

        # 2) 本季度费用汇总
        r = await db.execute(text("""
            SELECT COALESCE(SUM(total_amount), 0) AS quarter_total_fen
            FROM expense_applications
            WHERE tenant_id = :tid
              AND is_deleted = false
              AND status IN ('approved', 'paid')
              AND created_at::date BETWEEN :s AND :e
        """), {"tid": str(tenant_id), "s": q_start, "e": q_end})
        quarter_total_fen = int(r.scalar() or 0)

        # 3) 上月费用（环比）
        r = await db.execute(text("""
            SELECT COALESCE(SUM(total_amount), 0) AS prev_total_fen
            FROM expense_applications
            WHERE tenant_id = :tid
              AND is_deleted = false
              AND status IN ('approved', 'paid')
              AND created_at::date BETWEEN :s AND :e
        """), {"tid": str(tenant_id), "s": pm_start, "e": pm_end})
        prev_total_fen = int(r.scalar() or 0)

        mom_rate = None
        if prev_total_fen > 0:
            mom_rate = round((month_total_fen - prev_total_fen) / prev_total_fen * 100, 2)

        # 4) 待审批单据
        r = await db.execute(text("""
            SELECT COUNT(*) AS cnt, COALESCE(SUM(total_amount), 0) AS pending_fen
            FROM expense_applications
            WHERE tenant_id = :tid
              AND is_deleted = false
              AND status = 'pending_review'
        """), {"tid": str(tenant_id)})
        row = r.mappings().one()
        pending_count = int(row["cnt"])
        pending_fen = int(row["pending_fen"])

        # 5) 本月预算执行率（取月度预算，不存在时取年度）
        r = await db.execute(text("""
            SELECT total_amount, used_amount
            FROM budgets
            WHERE tenant_id = :tid
              AND is_deleted = false
              AND status = 'active'
              AND budget_year = :yr
              AND budget_month = :mo
            ORDER BY created_at DESC
            LIMIT 1
        """), {"tid": str(tenant_id), "yr": year, "mo": month})
        budget_row = r.mappings().first()
        if not budget_row:
            # fallback: 年度预算
            r = await db.execute(text("""
                SELECT total_amount, used_amount
                FROM budgets
                WHERE tenant_id = :tid
                  AND is_deleted = false
                  AND status = 'active'
                  AND budget_year = :yr
                  AND budget_month IS NULL
                ORDER BY created_at DESC
                LIMIT 1
            """), {"tid": str(tenant_id), "yr": year})
            budget_row = r.mappings().first()

        budget_total = int(budget_row["total_amount"]) if budget_row else None
        budget_used = int(budget_row["used_amount"]) if budget_row else None
        budget_rate = None
        if budget_total and budget_total > 0:
            budget_rate = round(budget_used / budget_total * 100, 2)

        # 6) 发票状态（本月）
        r = await db.execute(text("""
            SELECT
                COUNT(*) AS total_invoices,
                COUNT(*) FILTER (WHERE verification_status = 'pending_verification') AS pending_verify,
                COUNT(*) FILTER (WHERE verification_status = 'verified')             AS verified,
                COUNT(*) FILTER (WHERE verification_status = 'invalid')              AS invalid
            FROM invoices
            WHERE tenant_id = :tid
              AND is_deleted = false
              AND created_at::date BETWEEN :s AND :e
        """), {"tid": str(tenant_id), "s": m_start, "e": m_end})
        inv_row = r.mappings().first()
        invoice_stats = {
            "total": int(inv_row["total_invoices"]) if inv_row else 0,
            "pending_verify": int(inv_row["pending_verify"]) if inv_row else 0,
            "verified": int(inv_row["verified"]) if inv_row else 0,
            "invalid": int(inv_row["invalid"]) if inv_row else 0,
        }

        return _ok({
            "period": {"year": year, "month": month},
            "month_expense": {
                "total_fen": month_total_fen,
                "paid_fen": month_paid_fen,
                "count": month_count,
                "mom_rate": mom_rate,
            },
            "quarter_expense": {
                "total_fen": quarter_total_fen,
                "quarter": (month - 1) // 3 + 1,
            },
            "pending_approval": {
                "count": pending_count,
                "total_fen": pending_fen,
            },
            "budget": {
                "total_fen": budget_total,
                "used_fen": budget_used,
                "execution_rate": budget_rate,
            },
            "invoices": invoice_stats,
        })

    except SQLAlchemyError as e:
        log.error("dashboard_overview_error", error=str(e), tenant_id=str(tenant_id))
        raise HTTPException(status_code=500, detail="查询费控总览失败")


# ─────────────────────────────────────────────────────────────────────────────
# GET /by-store — 按门店维度汇总
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/by-store",
    summary="按门店费控汇总",
    description="返回各门店的当月费用总额，可关联每日成本日报中的成本率数据。",
)
async def get_by_store(
    year: Optional[int] = Query(None, ge=2020, le=2030),
    month: Optional[int] = Query(None, ge=1, le=12),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    _year, _month = _current_ym()
    year = year or _year
    month = month or _month
    m_start, m_end = _month_bounds(year, month)

    try:
        # 费控申请按门店汇总
        r = await db.execute(text("""
            SELECT
                store_id::text,
                COUNT(*) AS application_count,
                COALESCE(SUM(total_amount), 0) AS total_fen,
                COALESCE(SUM(CASE WHEN status='paid' THEN total_amount ELSE 0 END), 0) AS paid_fen,
                COALESCE(SUM(CASE WHEN status='pending_review' THEN total_amount ELSE 0 END), 0) AS pending_fen
            FROM expense_applications
            WHERE tenant_id = :tid
              AND is_deleted = false
              AND status NOT IN ('draft', 'rejected', 'cancelled')
              AND created_at::date BETWEEN :s AND :e
            GROUP BY store_id
            ORDER BY total_fen DESC
        """), {"tid": str(tenant_id), "s": m_start, "e": m_end})
        expense_rows = r.mappings().all()

        # 成本日报（本月均值）按门店
        r = await db.execute(text("""
            SELECT
                store_id::text,
                ROUND(AVG(food_cost_rate)::numeric, 4)     AS avg_food_cost_rate,
                ROUND(AVG(labor_cost_rate)::numeric, 4)    AS avg_labor_cost_rate,
                ROUND(AVG(gross_margin_rate)::numeric, 4)  AS avg_gross_margin_rate,
                COALESCE(SUM(total_revenue_fen), 0)        AS month_revenue_fen
            FROM daily_cost_reports
            WHERE tenant_id = :tid
              AND is_deleted = false
              AND report_date BETWEEN :s AND :e
              AND data_status != 'pending'
            GROUP BY store_id
        """), {"tid": str(tenant_id), "s": m_start, "e": m_end})
        cost_rows = {str(r["store_id"]): r for r in r.mappings().all()}

        stores = []
        for row in expense_rows:
            sid = row["store_id"]
            cr = cost_rows.get(sid, {})
            stores.append({
                "store_id": sid,
                "expense": {
                    "total_fen": int(row["total_fen"]),
                    "paid_fen": int(row["paid_fen"]),
                    "pending_fen": int(row["pending_fen"]),
                    "application_count": int(row["application_count"]),
                },
                "cost_report": {
                    "month_revenue_fen": int(cr["month_revenue_fen"]) if cr else None,
                    "avg_food_cost_rate": float(cr["avg_food_cost_rate"]) if cr and cr["avg_food_cost_rate"] else None,
                    "avg_labor_cost_rate": float(cr["avg_labor_cost_rate"]) if cr and cr["avg_labor_cost_rate"] else None,
                    "avg_gross_margin_rate": float(cr["avg_gross_margin_rate"]) if cr and cr["avg_gross_margin_rate"] else None,
                } if cr else None,
            })

        return _ok({
            "period": {"year": year, "month": month},
            "stores": stores,
            "total_stores": len(stores),
        })

    except SQLAlchemyError as e:
        log.error("dashboard_by_store_error", error=str(e), tenant_id=str(tenant_id))
        raise HTTPException(status_code=500, detail="按门店汇总查询失败")


# ─────────────────────────────────────────────────────────────────────────────
# GET /by-category — 按科目维度汇总
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/by-category",
    summary="按科目费控汇总",
    description="返回各费用科目的支出总额及占比，可用于分析科目支出结构。",
)
async def get_by_category(
    year: Optional[int] = Query(None, ge=2020, le=2030),
    month: Optional[int] = Query(None, ge=1, le=12),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    _year, _month = _current_ym()
    year = year or _year
    month = month or _month
    m_start, m_end = _month_bounds(year, month)

    try:
        r = await db.execute(text("""
            SELECT
                ea.category_id::text,
                ec.name            AS category_name,
                ec.parent_id::text AS parent_id,
                COUNT(ea.id)       AS application_count,
                COALESCE(SUM(ea.total_amount), 0) AS total_fen
            FROM expense_applications ea
            LEFT JOIN expense_categories ec
                   ON ec.id = ea.category_id AND ec.tenant_id = :tid AND ec.is_deleted = false
            WHERE ea.tenant_id = :tid
              AND ea.is_deleted = false
              AND ea.status IN ('approved', 'paid')
              AND ea.created_at::date BETWEEN :s AND :e
            GROUP BY ea.category_id, ec.name, ec.parent_id
            ORDER BY total_fen DESC
        """), {"tid": str(tenant_id), "s": m_start, "e": m_end})
        rows = r.mappings().all()

        grand_total = sum(int(r["total_fen"]) for r in rows)

        categories = []
        for row in rows:
            total = int(row["total_fen"])
            categories.append({
                "category_id": row["category_id"],
                "category_name": row["category_name"],
                "parent_id": row["parent_id"],
                "total_fen": total,
                "ratio": round(total / grand_total * 100, 2) if grand_total > 0 else 0,
                "application_count": int(row["application_count"]),
            })

        return _ok({
            "period": {"year": year, "month": month},
            "grand_total_fen": grand_total,
            "categories": categories,
        })

    except SQLAlchemyError as e:
        log.error("dashboard_by_category_error", error=str(e), tenant_id=str(tenant_id))
        raise HTTPException(status_code=500, detail="按科目汇总查询失败")


# ─────────────────────────────────────────────────────────────────────────────
# GET /trend — 费用趋势
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/trend",
    summary="费用趋势分析",
    description="返回最近 N 个月的月度费用趋势，含环比增长率。",
)
async def get_trend(
    months: int = Query(6, ge=1, le=24, description="回溯月数，默认6，最大24"),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        # 生成最近 months 个月的列表，从当月往前推
        today = date.today()
        periods = []
        y, m = today.year, today.month
        for _ in range(months):
            periods.append((y, m))
            m -= 1
            if m == 0:
                m = 12
                y -= 1
        periods.reverse()  # 从旧到新

        month_starts = [date(p[0], p[1], 1) for p in periods]
        month_ends = [date(p[0], p[1], calendar.monthrange(p[0], p[1])[1]) for p in periods]

        # 批量查询所有月份
        r = await db.execute(text("""
            SELECT
                DATE_TRUNC('month', created_at)::date AS month_start,
                COALESCE(SUM(total_amount), 0)        AS total_fen,
                COUNT(*)                              AS application_count
            FROM expense_applications
            WHERE tenant_id = :tid
              AND is_deleted = false
              AND status IN ('approved', 'paid')
              AND created_at::date BETWEEN :start AND :end
            GROUP BY DATE_TRUNC('month', created_at)
            ORDER BY month_start
        """), {
            "tid": str(tenant_id),
            "start": month_starts[0],
            "end": month_ends[-1],
        })
        rows_by_month = {row["month_start"]: row for row in r.mappings().all()}

        trend = []
        prev_total = None
        for (y2, m2), ms in zip(periods, month_starts):
            row = rows_by_month.get(ms)
            total = int(row["total_fen"]) if row else 0
            count = int(row["application_count"]) if row else 0
            mom = None
            if prev_total is not None and prev_total > 0:
                mom = round((total - prev_total) / prev_total * 100, 2)
            trend.append({
                "year": y2,
                "month": m2,
                "total_fen": total,
                "application_count": count,
                "mom_rate": mom,
            })
            prev_total = total

        return _ok({"months": months, "trend": trend})

    except SQLAlchemyError as e:
        log.error("dashboard_trend_error", error=str(e), tenant_id=str(tenant_id))
        raise HTTPException(status_code=500, detail="趋势查询失败")


# ─────────────────────────────────────────────────────────────────────────────
# GET /top-applicants — 高频申请人排行
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/top-applicants",
    summary="高频申请人排行",
    description="返回指定月份申请金额 TOP N 的申请人列表。",
)
async def get_top_applicants(
    year: Optional[int] = Query(None, ge=2020, le=2030),
    month: Optional[int] = Query(None, ge=1, le=12),
    limit: int = Query(10, ge=1, le=50),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    _year, _month = _current_ym()
    year = year or _year
    month = month or _month
    m_start, m_end = _month_bounds(year, month)

    try:
        r = await db.execute(text("""
            SELECT
                applicant_id::text,
                COUNT(*)                          AS application_count,
                COALESCE(SUM(total_amount), 0)   AS total_fen,
                COALESCE(AVG(total_amount), 0)   AS avg_fen,
                MAX(created_at)                  AS last_applied_at,
                COUNT(*) FILTER (WHERE status = 'pending_review') AS pending_count,
                COUNT(*) FILTER (WHERE status IN ('approved','paid')) AS approved_count,
                COUNT(*) FILTER (WHERE status = 'rejected') AS rejected_count
            FROM expense_applications
            WHERE tenant_id = :tid
              AND is_deleted = false
              AND status NOT IN ('draft', 'cancelled')
              AND created_at::date BETWEEN :s AND :e
            GROUP BY applicant_id
            ORDER BY total_fen DESC
            LIMIT :lim
        """), {"tid": str(tenant_id), "s": m_start, "e": m_end, "lim": limit})
        rows = r.mappings().all()

        applicants = []
        for i, row in enumerate(rows):
            applicants.append({
                "rank": i + 1,
                "applicant_id": row["applicant_id"],
                "application_count": int(row["application_count"]),
                "total_fen": int(row["total_fen"]),
                "avg_fen": int(row["avg_fen"]),
                "pending_count": int(row["pending_count"]),
                "approved_count": int(row["approved_count"]),
                "rejected_count": int(row["rejected_count"]),
                "last_applied_at": row["last_applied_at"].isoformat() if row["last_applied_at"] else None,
            })

        return _ok({
            "period": {"year": year, "month": month},
            "limit": limit,
            "applicants": applicants,
        })

    except SQLAlchemyError as e:
        log.error("dashboard_top_applicants_error", error=str(e), tenant_id=str(tenant_id))
        raise HTTPException(status_code=500, detail="申请人排行查询失败")
