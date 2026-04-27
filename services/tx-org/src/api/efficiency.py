"""人效指标 API"""

from datetime import date, timedelta
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, Query
from services.labor_efficiency_service import (
    INDUSTRY_BENCHMARKS,
    compare_stores,
    compute_store_efficiency,
    get_boss_view,
    get_hr_view,
    get_manager_view,
    get_staff_view,
)
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/org/efficiency", tags=["efficiency"])


# ── DB 辅助 ───────────────────────────────────────────────────────────────────


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ── 真实数据查询函数 ──────────────────────────────────────────────────────────


async def _get_store_data(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """查询门店最近30天的薪资、营收、考勤数据，组装为 labor_efficiency_service 所需字典。"""
    try:
        await _set_rls(db, tenant_id)

        cutoff = (date.today() - timedelta(days=30)).isoformat()

        # 薪资汇总（取最近一期）
        payroll_row = await db.execute(
            text("""
                SELECT total_salary_fen, headcount
                FROM payroll_summaries
                WHERE store_id = :sid
                  AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                ORDER BY period_year DESC, period_month DESC
                LIMIT 1
            """),
            {"sid": store_id},
        )
        payroll = payroll_row.mappings().first()

        # 营收汇总（最近30天已支付订单）
        revenue_row = await db.execute(
            text("""
                SELECT COALESCE(SUM(total_fen), 0) AS total_revenue_fen,
                       COUNT(*) AS order_count
                FROM orders
                WHERE store_id = :sid
                  AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  AND status = 'paid'
                  AND created_at >= :cutoff
            """),
            {"sid": store_id, "cutoff": cutoff},
        )
        revenue = revenue_row.mappings().first()

        # 出勤工时汇总（最近30天）
        attendance_row = await db.execute(
            text("""
                SELECT COALESCE(SUM(work_hours), 0.0) AS total_work_hours
                FROM daily_attendance
                WHERE store_id = :sid
                  AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  AND work_date >= :cutoff
            """),
            {"sid": store_id, "cutoff": cutoff},
        )
        attendance = attendance_row.mappings().first()

        total_labor_fen = int(payroll["total_salary_fen"]) if payroll and payroll["total_salary_fen"] else 0
        headcount = int(payroll["headcount"]) if payroll and payroll["headcount"] else 0
        total_revenue_fen = int(revenue["total_revenue_fen"]) if revenue else 0
        total_work_hours = float(attendance["total_work_hours"]) if attendance else 0.0
        # orders 表无 guest 字段，使用 order_count 近似客人数
        total_guests = int(revenue["order_count"]) if revenue else 0

        return {
            "store_id": store_id,
            "store_name": f"门店-{store_id}",
            "total_labor_fen": total_labor_fen,
            "total_revenue_fen": total_revenue_fen,
            "headcount": headcount,
            "total_work_hours": total_work_hours,
            "total_guests": total_guests,
            "productive_hours": total_work_hours,
            "total_hours": total_work_hours,
            "employees": [],
            "peak_hours": [],
            "scheduled_hours": total_work_hours,
            "required_hours": total_work_hours,
        }
    except (SQLAlchemyError, Exception) as exc:
        log.warning("_get_store_data failed, returning zeros", store_id=store_id, error=str(exc))
        return {
            "store_id": store_id,
            "store_name": f"门店-{store_id}",
            "total_labor_fen": 0,
            "total_revenue_fen": 0,
            "headcount": 0,
            "total_work_hours": 0.0,
            "total_guests": 0,
            "productive_hours": 0.0,
            "total_hours": 0.0,
            "employees": [],
            "peak_hours": [],
            "scheduled_hours": 0.0,
            "required_hours": 0.0,
        }


async def _get_brand_data(
    brand_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """聚合当前租户下所有门店的人效数据，组装为 labor_efficiency_service 所需字典。"""
    try:
        await _set_rls(db, tenant_id)

        cutoff = (date.today() - timedelta(days=30)).isoformat()

        # 获取租户下所有门店 ID（通过 payroll_summaries 或 employees 推断）
        store_rows = await db.execute(
            text("""
                SELECT DISTINCT store_id::text
                FROM employees
                WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  AND status = 'active'
            """),
        )
        store_ids = [r[0] for r in store_rows.fetchall()]

        stores = [await _get_store_data(sid, tenant_id, db) for sid in store_ids]

        # 近3个月薪资/营收趋势（按月聚合）
        trend_rows = await db.execute(
            text("""
                SELECT period_year, period_month,
                       SUM(total_salary_fen) AS monthly_labor_fen
                FROM payroll_summaries
                WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                GROUP BY period_year, period_month
                ORDER BY period_year DESC, period_month DESC
                LIMIT 3
            """),
        )
        trend = trend_rows.mappings().all()
        monthly_labor_fen = [int(r["monthly_labor_fen"]) for r in reversed(trend)]

        revenue_trend_rows = await db.execute(
            text("""
                SELECT DATE_TRUNC('month', created_at) AS mo,
                       SUM(total_fen) AS monthly_revenue_fen
                FROM orders
                WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  AND status = 'paid'
                  AND created_at >= :cutoff
                GROUP BY mo
                ORDER BY mo DESC
                LIMIT 3
            """),
            {"cutoff": cutoff},
        )
        rev_trend = revenue_trend_rows.mappings().all()
        monthly_revenue_fen = [int(r["monthly_revenue_fen"]) for r in reversed(rev_trend)]

        # 员工汇总统计
        headcount_row = await db.execute(
            text("""
                SELECT COUNT(*) AS total_headcount
                FROM employees
                WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  AND status = 'active'
            """),
        )
        total_headcount = int((headcount_row.scalar()) or 0)

        # 平均薪资（最近一期 payroll_summaries）
        avg_salary_row = await db.execute(
            text("""
                SELECT AVG(total_salary_fen::float / NULLIF(headcount, 0)) AS avg_salary_fen
                FROM payroll_summaries
                WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  AND period_year = (
                      SELECT MAX(period_year) FROM payroll_summaries
                      WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  )
            """),
        )
        avg_salary_fen = int((avg_salary_row.scalar()) or 0)

        return {
            "brand_id": brand_id,
            "brand_name": f"品牌-{brand_id}",
            "stores": stores,
            "monthly_labor_fen": monthly_labor_fen,
            "monthly_revenue_fen": monthly_revenue_fen,
            "total_headcount": total_headcount,
            "total_positions": total_headcount,
            "resignations_this_month": 0,
            "avg_tenure_months": 0,
            "open_positions": 0,
            "avg_salary_fen": avg_salary_fen,
        }
    except (SQLAlchemyError, Exception) as exc:
        log.warning("_get_brand_data failed, returning zeros", brand_id=brand_id, error=str(exc))
        return {
            "brand_id": brand_id,
            "brand_name": f"品牌-{brand_id}",
            "stores": [],
            "monthly_labor_fen": [],
            "monthly_revenue_fen": [],
            "total_headcount": 0,
            "total_positions": 0,
            "resignations_this_month": 0,
            "avg_tenure_months": 0,
            "open_positions": 0,
            "avg_salary_fen": 0,
        }


async def _get_employee_data(
    employee_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """查询单个员工最近30天的出勤、薪资及所在门店营收，组装为 labor_efficiency_service 所需字典。"""
    try:
        await _set_rls(db, tenant_id)

        cutoff = (date.today() - timedelta(days=30)).isoformat()

        # 员工基本信息 + 门店
        emp_row = await db.execute(
            text("""
                SELECT employee_id::text, store_id::text
                FROM employees
                WHERE employee_id = :eid
                  AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                LIMIT 1
            """),
            {"eid": employee_id},
        )
        emp = emp_row.mappings().first()
        store_id = emp["store_id"] if emp else None

        # 出勤工时
        attendance_row = await db.execute(
            text("""
                SELECT COALESCE(SUM(work_hours), 0.0) AS hours_worked,
                       COUNT(*) FILTER (WHERE status = 'present') AS present_days,
                       COUNT(*) FILTER (WHERE status = 'absent')  AS absent_days,
                       COUNT(*) FILTER (WHERE status = 'late')    AS late_count,
                       COUNT(*) FILTER (WHERE status = 'early_leave') AS early_leave_count
                FROM daily_attendance
                WHERE employee_id = :eid
                  AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  AND work_date >= :cutoff
            """),
            {"eid": employee_id, "cutoff": cutoff},
        )
        att = attendance_row.mappings().first()

        # 薪资（最近一期）
        payroll_row = await db.execute(
            text("""
                SELECT total_salary_fen
                FROM payroll_summaries
                WHERE store_id = :sid
                  AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                ORDER BY period_year DESC, period_month DESC
                LIMIT 1
            """),
            {"sid": store_id or ""},
        )
        payroll = payroll_row.mappings().first()
        total_salary_fen = int(payroll["total_salary_fen"]) if payroll and payroll["total_salary_fen"] else 0

        # 所在门店营收（近30天，用于计算人均产值）
        revenue_row = await db.execute(
            text("""
                SELECT COALESCE(SUM(total_fen), 0) AS revenue_fen,
                       COUNT(*) AS order_count
                FROM orders
                WHERE store_id = :sid
                  AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  AND status = 'paid'
                  AND created_at >= :cutoff
            """),
            {"sid": store_id or "", "cutoff": cutoff},
        )
        rev = revenue_row.mappings().first()

        return {
            "emp_id": employee_id,
            "emp_name": f"员工-{employee_id}",
            "hours_worked": float(att["hours_worked"]) if att else 0.0,
            "revenue_fen": int(rev["revenue_fen"]) if rev else 0,
            "guests_served": int(rev["order_count"]) if rev else 0,
            "attendance": {
                "present_days": int(att["present_days"]) if att else 0,
                "absent_days": int(att["absent_days"]) if att else 0,
                "late_count": int(att["late_count"]) if att else 0,
                "early_leave_count": int(att["early_leave_count"]) if att else 0,
            },
            "salary": {
                "base_fen": total_salary_fen,
                "commission_fen": 0,
                "bonus_fen": 0,
                "deduction_fen": 0,
                "net_fen": total_salary_fen,
            },
        }
    except (SQLAlchemyError, Exception) as exc:
        log.warning("_get_employee_data failed, returning zeros", employee_id=employee_id, error=str(exc))
        return {
            "emp_id": employee_id,
            "emp_name": f"员工-{employee_id}",
            "hours_worked": 0.0,
            "revenue_fen": 0,
            "guests_served": 0,
            "attendance": {
                "present_days": 0,
                "absent_days": 0,
                "late_count": 0,
                "early_leave_count": 0,
            },
            "salary": {
                "base_fen": 0,
                "commission_fen": 0,
                "bonus_fen": 0,
                "deduction_fen": 0,
                "net_fen": 0,
            },
        }


# ── API 端点 ──────────────────────────────────────────────────────────────────


@router.get("/benchmark")
async def get_benchmark():
    """行业基准值。"""
    return {"ok": True, "data": INDUSTRY_BENCHMARKS}


@router.get("/compare")
async def get_compare(
    store_ids: str = Query(..., description="逗号分隔的门店ID列表"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """多门店人效对比。"""
    ids = [sid.strip() for sid in store_ids.split(",") if sid.strip()]
    stores_data = [await _get_store_data(sid, x_tenant_id, db) for sid in ids]
    result = compare_stores(stores_data)
    return {"ok": True, "data": result}


@router.get("/alerts")
async def get_alerts(
    store_id: Optional[str] = None,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """人效预警。"""
    if store_id:
        sd = await _get_store_data(store_id, x_tenant_id, db)
        report = compute_store_efficiency(sd)
        alerts = report["alerts"]
    else:
        brand = await _get_brand_data("default", x_tenant_id, db)
        alerts = []
        for sd in brand["stores"]:
            report = compute_store_efficiency(sd)
            for alert in report["alerts"]:
                alert["store_id"] = sd["store_id"]
                alert["store_name"] = sd["store_name"]
                alerts.append(alert)
    return {"ok": True, "data": {"alerts": alerts}}


@router.get("/dashboard")
async def get_dashboard(
    role: str = Query(..., description="角色: boss|hr|manager|staff"),
    store_id: Optional[str] = None,
    emp_id: Optional[str] = None,
    brand_id: Optional[str] = None,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """多角色看板。"""
    if role == "boss":
        data = get_boss_view(await _get_brand_data(brand_id or "default", x_tenant_id, db))
    elif role == "hr":
        data = get_hr_view(await _get_brand_data(brand_id or "default", x_tenant_id, db))
    elif role == "manager":
        sd = await _get_store_data(store_id or "", x_tenant_id, db)
        data = get_manager_view(sd)
    elif role == "staff":
        data = get_staff_view(await _get_employee_data(emp_id or "", x_tenant_id, db))
    else:
        return {
            "ok": False,
            "error": {"code": "INVALID_ROLE", "message": f"不支持的角色: {role}，请使用 boss|hr|manager|staff"},
        }
    return {"ok": True, "data": data}


@router.get("/{store_id}")
async def get_store_efficiency(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """门店人效报告。"""
    sd = await _get_store_data(store_id, x_tenant_id, db)
    report = compute_store_efficiency(sd)
    return {"ok": True, "data": report}
