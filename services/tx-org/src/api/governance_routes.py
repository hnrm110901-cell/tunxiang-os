"""总部人力治理台 API 路由

端点列表：
  GET /api/v1/hr/governance/dashboard     总部人力驾驶舱聚合数据
  GET /api/v1/hr/governance/benchmark     门店对标数据
  GET /api/v1/hr/governance/staffing      编制治理
  GET /api/v1/hr/governance/risk-stores   高风险门店

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/hr/governance", tags=["governance"])


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get(
        "X-Tenant-ID", ""
    )
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ── 端点 ──────────────────────────────────────────────────────────────────────


@router.get("/dashboard")
async def governance_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """总部人力驾驶舱聚合数据：全集团在职人数（按品牌/区域）、出勤率、人工成本率、人均产出。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 在职人数统计（按品牌/区域）
    headcount_q = text("""
        SELECT
            COALESCE(s.brand, '未知品牌') AS brand,
            COALESCE(s.city, '未知') AS region,
            COUNT(DISTINCT e.id) AS headcount
        FROM employees e
        LEFT JOIN stores s ON s.id = e.store_id AND s.tenant_id = e.tenant_id
        WHERE e.tenant_id = CAST(:tenant_id AS uuid)
          AND e.is_deleted = false
          AND COALESCE(e.is_active, true) = true
        GROUP BY s.brand, s.city
        ORDER BY headcount DESC
    """)

    # 平均出勤率（近30天）
    attendance_q = text("""
        SELECT
            COUNT(CASE WHEN da.status = 'normal' THEN 1 END)::float
            / GREATEST(COUNT(*), 1) AS avg_attendance_rate
        FROM daily_attendance da
        WHERE da.tenant_id = CAST(:tenant_id AS uuid)
          AND COALESCE(da.is_deleted, false) = false
          AND da.date >= CURRENT_DATE - 30
    """)

    # 人均产出（近30天 — 从 orders 或 mv_store_pnl 聚合）
    productivity_q = text("""
        SELECT
            COALESCE(SUM(o.total_fen), 0)::bigint AS total_revenue_fen,
            COUNT(DISTINCT e.id) AS active_employees
        FROM employees e
        LEFT JOIN orders o
          ON o.store_id = e.store_id
          AND o.tenant_id = e.tenant_id
          AND o.status = 'paid'
          AND o.created_at >= CURRENT_DATE - 30
        WHERE e.tenant_id = CAST(:tenant_id AS uuid)
          AND e.is_deleted = false
          AND COALESCE(e.is_active, true) = true
    """)

    try:
        hc_result = await db.execute(headcount_q, {"tenant_id": tenant_id})
        hc_rows = [dict(r) for r in hc_result.mappings()]
    except (OperationalError, ProgrammingError) as exc:
        log.warning("governance_headcount_failed", error=str(exc))
        hc_rows = []

    total_headcount = sum(r.get("headcount", 0) for r in hc_rows)
    by_brand: dict[str, int] = {}
    by_region: dict[str, int] = {}
    for r in hc_rows:
        brand = str(r.get("brand") or "未知品牌")
        region = str(r.get("region") or "未知")
        by_brand[brand] = by_brand.get(brand, 0) + int(r.get("headcount", 0))
        by_region[region] = by_region.get(region, 0) + int(r.get("headcount", 0))

    try:
        att_result = await db.execute(attendance_q, {"tenant_id": tenant_id})
        att_row = att_result.mappings().first()
        avg_attendance_rate = round(float(att_row["avg_attendance_rate"]) * 100, 1) if att_row else 0
    except (OperationalError, ProgrammingError) as exc:
        log.warning("governance_attendance_failed", error=str(exc))
        avg_attendance_rate = 0

    try:
        prod_result = await db.execute(productivity_q, {"tenant_id": tenant_id})
        prod_row = prod_result.mappings().first()
        total_rev = int(prod_row["total_revenue_fen"]) if prod_row else 0
        active_emp = int(prod_row["active_employees"]) if prod_row else 1
        productivity_per_person_fen = total_rev // max(1, active_emp)
    except (OperationalError, ProgrammingError) as exc:
        log.warning("governance_productivity_failed", error=str(exc))
        productivity_per_person_fen = 0

    return _ok({
        "total_headcount": total_headcount,
        "by_brand": by_brand,
        "by_region": by_region,
        "avg_attendance_rate": avg_attendance_rate,
        "avg_labor_cost_rate": 0,  # TODO: 接入 payroll 数据计算
        "productivity_per_person_fen": productivity_per_person_fen,
    })


@router.get("/benchmark")
async def governance_benchmark(
    request: Request,
    metric: str = Query(
        default="attendance_rate",
        description="对标指标: attendance_rate/labor_cost_rate/productivity/work_hours",
    ),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """门店对标数据：各门店指标值 + 排名 + 与均值差异。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    if metric == "attendance_rate":
        q = text("""
            SELECT
                da.store_id,
                COALESCE(s.name, da.store_id) AS store_name,
                COUNT(CASE WHEN da.status = 'normal' THEN 1 END)::float
                  / GREATEST(COUNT(*), 1) AS metric_value
            FROM daily_attendance da
            LEFT JOIN stores s ON s.id::text = da.store_id AND s.tenant_id = da.tenant_id
            WHERE da.tenant_id = CAST(:tenant_id AS uuid)
              AND COALESCE(da.is_deleted, false) = false
              AND da.date >= CURRENT_DATE - 30
            GROUP BY da.store_id, s.name
            ORDER BY metric_value DESC
        """)
    elif metric == "productivity":
        q = text("""
            SELECT
                e.store_id::text AS store_id,
                COALESCE(s.name, e.store_id::text) AS store_name,
                COALESCE(SUM(o.total_fen), 0)::float
                  / GREATEST(COUNT(DISTINCT e.id), 1) AS metric_value
            FROM employees e
            LEFT JOIN stores s ON s.id = e.store_id AND s.tenant_id = e.tenant_id
            LEFT JOIN orders o
              ON o.store_id = e.store_id AND o.tenant_id = e.tenant_id
              AND o.status = 'paid' AND o.created_at >= CURRENT_DATE - 30
            WHERE e.tenant_id = CAST(:tenant_id AS uuid)
              AND e.is_deleted = false AND COALESCE(e.is_active, true) = true
            GROUP BY e.store_id, s.name
            ORDER BY metric_value DESC
        """)
    elif metric == "work_hours":
        q = text("""
            SELECT
                da.store_id,
                COALESCE(s.name, da.store_id) AS store_name,
                COALESCE(AVG(da.work_hours), 0)::float AS metric_value
            FROM daily_attendance da
            LEFT JOIN stores s ON s.id::text = da.store_id AND s.tenant_id = da.tenant_id
            WHERE da.tenant_id = CAST(:tenant_id AS uuid)
              AND COALESCE(da.is_deleted, false) = false
              AND da.date >= CURRENT_DATE - 30
              AND da.work_hours IS NOT NULL
            GROUP BY da.store_id, s.name
            ORDER BY metric_value DESC
        """)
    else:
        # labor_cost_rate — 需要薪资数据，暂 mock
        return _ok({
            "metric": metric,
            "stores": [],
            "average": 0,
            "note": "劳动力成本率需接入薪资模块，暂无数据",
        })

    try:
        result = await db.execute(q, {"tenant_id": tenant_id})
        rows = [dict(r) for r in result.mappings()]
    except (OperationalError, ProgrammingError) as exc:
        log.warning("governance_benchmark_failed", metric=metric, error=str(exc))
        rows = []

    if not rows:
        return _ok({"metric": metric, "stores": [], "average": 0})

    values = [float(r.get("metric_value") or 0) for r in rows]
    avg_val = sum(values) / max(1, len(values))

    stores = []
    for rank, r in enumerate(rows, 1):
        val = float(r.get("metric_value") or 0)
        stores.append({
            "store_id": str(r.get("store_id") or ""),
            "store_name": str(r.get("store_name") or ""),
            "metric_value": round(val, 4),
            "rank": rank,
            "diff_from_avg": round(val - avg_val, 4),
        })

    return _ok({
        "metric": metric,
        "stores": stores,
        "average": round(avg_val, 4),
    })


@router.get("/staffing")
async def governance_staffing(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """编制治理：各门店编制数 vs 实际人数 vs 缺编/超编。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    q = text("""
        SELECT
            s.id::text AS store_id,
            s.name AS store_name,
            COALESCE(s.staffing_target, 10) AS staffing_target,
            COUNT(DISTINCT e.id) AS actual_count
        FROM stores s
        LEFT JOIN employees e
          ON e.store_id = s.id AND e.tenant_id = s.tenant_id
          AND e.is_deleted = false AND COALESCE(e.is_active, true) = true
        WHERE s.tenant_id = CAST(:tenant_id AS uuid)
          AND COALESCE(s.is_deleted, false) = false
        GROUP BY s.id, s.name, s.staffing_target
        ORDER BY s.name
    """)

    try:
        result = await db.execute(q, {"tenant_id": tenant_id})
        rows = [dict(r) for r in result.mappings()]
    except (OperationalError, ProgrammingError) as exc:
        log.warning("governance_staffing_failed", error=str(exc))
        rows = []

    stores = []
    total_target = 0
    total_actual = 0
    for r in rows:
        target = int(r.get("staffing_target") or 10)
        actual = int(r.get("actual_count") or 0)
        diff = actual - target
        total_target += target
        total_actual += actual
        stores.append({
            "store_id": str(r.get("store_id") or ""),
            "store_name": str(r.get("store_name") or ""),
            "staffing_target": target,
            "actual_count": actual,
            "diff": diff,
            "status": "over" if diff > 0 else ("under" if diff < 0 else "balanced"),
        })

    return _ok({
        "stores": stores,
        "total_target": total_target,
        "total_actual": total_actual,
        "total_diff": total_actual - total_target,
    })


@router.get("/risk-stores")
async def governance_risk_stores(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """高风险门店：综合评分排序。

    综合评分 = 出勤率×0.3 + (1-迟到率)×0.2 + (1-合规预警率)×0.3 + (1-成本率偏差)×0.2
    """
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 出勤率 + 迟到率
    att_q = text("""
        SELECT
            da.store_id,
            COALESCE(s.name, da.store_id) AS store_name,
            COUNT(*) AS total_records,
            COUNT(CASE WHEN da.status = 'normal' THEN 1 END)::float
              / GREATEST(COUNT(*), 1) AS attendance_rate,
            COUNT(CASE WHEN da.status = 'late' THEN 1 END)::float
              / GREATEST(COUNT(*), 1) AS late_rate
        FROM daily_attendance da
        LEFT JOIN stores s ON s.id::text = da.store_id AND s.tenant_id = da.tenant_id
        WHERE da.tenant_id = CAST(:tenant_id AS uuid)
          AND COALESCE(da.is_deleted, false) = false
          AND da.date >= CURRENT_DATE - 30
        GROUP BY da.store_id, s.name
    """)

    # 合规预警率
    alert_q = text("""
        SELECT
            ca.store_id,
            COUNT(CASE WHEN ca.status = 'open' THEN 1 END)::float
              / GREATEST(COUNT(*), 1) AS alert_rate
        FROM compliance_alerts ca
        WHERE ca.tenant_id = CAST(:tenant_id AS uuid)
          AND ca.created_at >= CURRENT_DATE - 30
        GROUP BY ca.store_id
    """)

    try:
        att_result = await db.execute(att_q, {"tenant_id": tenant_id})
        att_rows = {str(r["store_id"]): dict(r) for r in att_result.mappings()}
    except (OperationalError, ProgrammingError) as exc:
        log.warning("governance_risk_att_failed", error=str(exc))
        att_rows = {}

    alert_map: dict[str, float] = {}
    try:
        alert_result = await db.execute(alert_q, {"tenant_id": tenant_id})
        for r in alert_result.mappings():
            alert_map[str(r["store_id"])] = float(r["alert_rate"])
    except (OperationalError, ProgrammingError) as exc:
        log.warning("governance_risk_alert_failed", error=str(exc))

    stores: list[dict[str, Any]] = []
    for store_id, att in att_rows.items():
        attendance_rate = float(att.get("attendance_rate") or 0)
        late_rate = float(att.get("late_rate") or 0)
        alert_rate = alert_map.get(store_id, 0)
        cost_deviation = 0  # TODO: 接入薪资模块

        # 综合评分（越高越好）
        score = (
            attendance_rate * 0.3
            + (1.0 - late_rate) * 0.2
            + (1.0 - alert_rate) * 0.3
            + (1.0 - cost_deviation) * 0.2
        )

        stores.append({
            "store_id": store_id,
            "store_name": str(att.get("store_name") or ""),
            "attendance_rate": round(attendance_rate, 4),
            "late_rate": round(late_rate, 4),
            "alert_rate": round(alert_rate, 4),
            "cost_deviation": round(cost_deviation, 4),
            "composite_score": round(score, 4),
            "total_records": int(att.get("total_records") or 0),
        })

    # 按评分升序（低分=高风险）
    stores.sort(key=lambda s: s["composite_score"])

    return _ok({
        "stores": stores,
        "total_stores": len(stores),
    })
