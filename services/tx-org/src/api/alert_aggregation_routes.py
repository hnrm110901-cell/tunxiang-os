"""AI 预警聚合引擎 API 路由（Human Hub 聚合分析层）

在 Sprint 1 已有的 ai_alert_routes 基础上，增加聚合分析与智能洞察。

端点列表（8个）：
  GET  /api/v1/alert-aggregation/risk-matrix           风险矩阵（门店×预警类型）
  GET  /api/v1/alert-aggregation/trend-analysis         预警趋势分析
  GET  /api/v1/alert-aggregation/store-risk-ranking     门店风险排名
  GET  /api/v1/alert-aggregation/employee-risk-profile  员工风险画像
  GET  /api/v1/alert-aggregation/problem-stores         问题店列表
  GET  /api/v1/alert-aggregation/action-effectiveness   预警处理效率分析
  GET  /api/v1/alert-aggregation/hub-overview           人力中枢总览数据
  GET  /api/v1/alert-aggregation/weekly-digest          周度人力简报

数据源：ai_alerts + dri_work_orders + store_readiness_scores
       + peak_guard_records + onboarding_paths
       + position_certifications + mentorship_relations

统一响应格式: {"ok": bool, "data": {}, "error": null}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from typing import Any, List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/alert-aggregation", tags=["alert-aggregation"])

SEVERITY_WEIGHT = {"critical": 3, "warning": 2, "info": 1}


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


# ── 1. 风险矩阵 ─────────────────────────────────────────────────────────────


@router.get("/risk-matrix")
async def get_risk_matrix(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """门店×预警类型的风险矩阵，severity 加权评分。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    sql = text("""
        SELECT store_id, alert_type,
            COUNT(*) FILTER (WHERE severity = 'critical') AS critical_count,
            COUNT(*) FILTER (WHERE severity = 'warning')  AS warning_count,
            COUNT(*) FILTER (WHERE severity = 'info')     AS info_count,
            COUNT(*) AS total
        FROM ai_alerts
        WHERE tenant_id = :tid AND resolved = FALSE AND is_deleted = FALSE
        GROUP BY store_id, alert_type
    """)
    rows = (await db.execute(sql, {"tid": tenant_id})).mappings().all()

    stores: set[str] = set()
    alert_types: set[str] = set()
    matrix: list[dict] = []
    for r in rows:
        sid = str(r["store_id"])
        at = r["alert_type"]
        stores.add(sid)
        alert_types.add(at)
        matrix.append({
            "store_id": sid,
            "alert_type": at,
            "critical_count": r["critical_count"],
            "warning_count": r["warning_count"],
            "info_count": r["info_count"],
            "total": r["total"],
            "weighted_score": (
                r["critical_count"] * 3
                + r["warning_count"] * 2
                + r["info_count"] * 1
            ),
        })

    return _ok({
        "matrix": matrix,
        "stores": sorted(stores),
        "alert_types": sorted(alert_types),
    })


# ── 2. 预警趋势分析 ──────────────────────────────────────────────────────────


@router.get("/trend-analysis")
async def get_trend_analysis(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    group_by: str = Query("day", regex="^(day|week)$"),
    db: AsyncSession = Depends(get_db),
):
    """最近 N 天/周，按 alert_type 分组的新增/解决/净增趋势。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    since = datetime.now(timezone.utc) - timedelta(days=days)
    sql = text("""
        SELECT DATE_TRUNC(:group_by, created_at) AS period,
            alert_type,
            COUNT(*) AS new_count,
            COUNT(*) FILTER (WHERE resolved = TRUE) AS resolved_count
        FROM ai_alerts
        WHERE tenant_id = :tid AND created_at >= :since AND is_deleted = FALSE
        GROUP BY period, alert_type
        ORDER BY period
    """)
    rows = (await db.execute(sql, {
        "tid": tenant_id,
        "group_by": group_by,
        "since": since,
    })).mappings().all()

    trends = [
        {
            "period": r["period"].isoformat() if r["period"] else None,
            "alert_type": r["alert_type"],
            "new_count": r["new_count"],
            "resolved_count": r["resolved_count"],
            "net_change": r["new_count"] - r["resolved_count"],
        }
        for r in rows
    ]
    return _ok({"days": days, "group_by": group_by, "trends": trends})


# ── 3. 门店风险排名 ──────────────────────────────────────────────────────────


@router.get("/store-risk-ranking")
async def get_store_risk_ranking(
    request: Request,
    top_n: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """综合评分：未解决预警加权分 + 就绪度反向分 + 覆盖度反向分。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    sql = text("""
        WITH alert_scores AS (
            SELECT store_id,
                SUM(CASE severity
                    WHEN 'critical' THEN 3
                    WHEN 'warning'  THEN 2
                    ELSE 1
                END) AS alert_score
            FROM ai_alerts
            WHERE tenant_id = :tid AND resolved = FALSE AND is_deleted = FALSE
            GROUP BY store_id
        ),
        readiness AS (
            SELECT DISTINCT ON (store_id) store_id, overall_score
            FROM store_readiness_scores
            WHERE tenant_id = :tid AND is_deleted = FALSE
            ORDER BY store_id, created_at DESC
        ),
        coverage AS (
            SELECT store_id, AVG(coverage_score) AS avg_coverage
            FROM peak_guard_records
            WHERE tenant_id = :tid AND is_deleted = FALSE
                AND created_at >= NOW() - INTERVAL '7 days'
            GROUP BY store_id
        )
        SELECT
            COALESCE(a.store_id, r.store_id, c.store_id) AS store_id,
            COALESCE(a.alert_score, 0) AS alert_score,
            GREATEST(0, 80 - COALESCE(r.overall_score, 0)) AS readiness_penalty,
            GREATEST(0, 60 - COALESCE(c.avg_coverage, 0)) AS coverage_penalty,
            (
                COALESCE(a.alert_score, 0)
                + GREATEST(0, 80 - COALESCE(r.overall_score, 0))
                + GREATEST(0, 60 - COALESCE(c.avg_coverage, 0))
            ) AS risk_score
        FROM alert_scores a
        FULL OUTER JOIN readiness r ON a.store_id = r.store_id
        FULL OUTER JOIN coverage c ON COALESCE(a.store_id, r.store_id) = c.store_id
        ORDER BY risk_score DESC
        LIMIT :top_n
    """)
    rows = (await db.execute(sql, {"tid": tenant_id, "top_n": top_n})).mappings().all()

    ranking = [
        {
            "store_id": str(r["store_id"]),
            "alert_score": float(r["alert_score"]),
            "readiness_penalty": float(r["readiness_penalty"]),
            "coverage_penalty": float(r["coverage_penalty"]),
            "risk_score": float(r["risk_score"]),
        }
        for r in rows
    ]
    return _ok({"top_n": top_n, "ranking": ranking})


# ── 4. 员工风险画像 ──────────────────────────────────────────────────────────


@router.get("/employee-risk-profile")
async def get_employee_risk_profile(
    request: Request,
    employee_id: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
):
    """指定员工的综合风险画像：预警+培训进度+认证状态+带教关系。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 相关预警
    alerts_sql = text("""
        SELECT id, alert_type, severity, title, resolved, created_at
        FROM ai_alerts
        WHERE tenant_id = :tid AND employee_id = :eid AND is_deleted = FALSE
        ORDER BY created_at DESC
    """)
    alert_rows = (await db.execute(alerts_sql, {
        "tid": tenant_id, "eid": employee_id,
    })).mappings().all()

    # 训练进度
    training_sql = text("""
        SELECT id, path_name, status, progress_pct, started_at, expected_end, completed_at
        FROM onboarding_paths
        WHERE tenant_id = :tid AND employee_id = :eid AND is_deleted = FALSE
        ORDER BY created_at DESC
    """)
    training_rows = (await db.execute(training_sql, {
        "tid": tenant_id, "eid": employee_id,
    })).mappings().all()

    # 认证状态
    cert_sql = text("""
        SELECT id, position_name, cert_status, score, certified_at, expires_at
        FROM position_certifications
        WHERE tenant_id = :tid AND employee_id = :eid AND is_deleted = FALSE
        ORDER BY created_at DESC
    """)
    cert_rows = (await db.execute(cert_sql, {
        "tid": tenant_id, "eid": employee_id,
    })).mappings().all()

    # 带教关系
    mentor_sql = text("""
        SELECT id, mentor_id, mentee_id, status, avg_score, started_at
        FROM mentorship_relations
        WHERE tenant_id = :tid
            AND (mentee_id = :eid OR mentor_id = :eid)
            AND is_deleted = FALSE
        ORDER BY created_at DESC
    """)
    mentor_rows = (await db.execute(mentor_sql, {
        "tid": tenant_id, "eid": employee_id,
    })).mappings().all()

    def _row_to_dict(r: Any) -> dict:
        d = dict(r)
        for k, v in d.items():
            if isinstance(v, (datetime, date)):
                d[k] = v.isoformat()
            elif isinstance(v, UUID):
                d[k] = str(v)
        return d

    return _ok({
        "employee_id": employee_id,
        "alerts": [_row_to_dict(r) for r in alert_rows],
        "training": [_row_to_dict(r) for r in training_rows],
        "certifications": [_row_to_dict(r) for r in cert_rows],
        "mentorship": [_row_to_dict(r) for r in mentor_rows],
    })


# ── 5. 问题店列表 ────────────────────────────────────────────────────────────


@router.get("/problem-stores")
async def get_problem_stores(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """critical预警>=2 或 就绪度red 或 peak覆盖度<60 的门店。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    sql = text("""
        WITH critical_stores AS (
            SELECT store_id, COUNT(*) AS critical_count
            FROM ai_alerts
            WHERE tenant_id = :tid AND resolved = FALSE
                AND is_deleted = FALSE AND severity = 'critical'
            GROUP BY store_id
            HAVING COUNT(*) >= 2
        ),
        red_stores AS (
            SELECT DISTINCT ON (store_id) store_id, risk_level, overall_score
            FROM store_readiness_scores
            WHERE tenant_id = :tid AND is_deleted = FALSE
            ORDER BY store_id, created_at DESC
        ),
        low_coverage_stores AS (
            SELECT store_id, AVG(coverage_score) AS avg_coverage
            FROM peak_guard_records
            WHERE tenant_id = :tid AND is_deleted = FALSE
                AND created_at >= NOW() - INTERVAL '7 days'
            GROUP BY store_id
            HAVING AVG(coverage_score) < 60
        )
        SELECT
            s.store_id,
            COALESCE(cs.critical_count, 0) AS critical_count,
            rs.risk_level,
            COALESCE(rs.overall_score, 0) AS readiness_score,
            COALESCE(lc.avg_coverage, 0) AS avg_coverage,
            ARRAY_REMOVE(ARRAY[
                CASE WHEN cs.store_id IS NOT NULL THEN 'high_critical' END,
                CASE WHEN rs.risk_level = 'red' THEN 'red_readiness' END,
                CASE WHEN lc.store_id IS NOT NULL THEN 'low_coverage' END
            ], NULL) AS problem_reasons
        FROM (
            SELECT store_id FROM critical_stores
            UNION
            SELECT store_id FROM red_stores WHERE risk_level = 'red'
            UNION
            SELECT store_id FROM low_coverage_stores
        ) s
        LEFT JOIN critical_stores cs ON s.store_id = cs.store_id
        LEFT JOIN red_stores rs ON s.store_id = rs.store_id
        LEFT JOIN low_coverage_stores lc ON s.store_id = lc.store_id
        ORDER BY COALESCE(cs.critical_count, 0) DESC
    """)
    rows = (await db.execute(sql, {"tid": tenant_id})).mappings().all()

    stores = [
        {
            "store_id": str(r["store_id"]),
            "critical_count": r["critical_count"],
            "risk_level": r["risk_level"],
            "readiness_score": float(r["readiness_score"]),
            "avg_coverage": float(r["avg_coverage"]),
            "problem_reasons": list(r["problem_reasons"]),
        }
        for r in rows
    ]
    return _ok({"total": len(stores), "stores": stores})


# ── 6. 预警处理效率分析 ──────────────────────────────────────────────────────


@router.get("/action-effectiveness")
async def get_action_effectiveness(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """平均解决时间/解决率/按类型对比/DRI工单转化率。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 总体指标
    overall_sql = text("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE resolved = TRUE) AS resolved,
            AVG(EXTRACT(EPOCH FROM (resolved_at - created_at)) / 3600)
                FILTER (WHERE resolved = TRUE) AS avg_resolution_hours,
            COUNT(*) FILTER (WHERE linked_order_id IS NOT NULL) AS with_order
        FROM ai_alerts
        WHERE tenant_id = :tid AND is_deleted = FALSE
    """)
    ov = (await db.execute(overall_sql, {"tid": tenant_id})).mappings().one()

    total = ov["total"] or 0
    resolved = ov["resolved"] or 0

    # 按类型分组
    by_type_sql = text("""
        SELECT
            alert_type,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE resolved = TRUE) AS resolved,
            AVG(EXTRACT(EPOCH FROM (resolved_at - created_at)) / 3600)
                FILTER (WHERE resolved = TRUE) AS avg_resolution_hours
        FROM ai_alerts
        WHERE tenant_id = :tid AND is_deleted = FALSE
        GROUP BY alert_type
    """)
    type_rows = (await db.execute(by_type_sql, {"tid": tenant_id})).mappings().all()

    by_type = [
        {
            "alert_type": r["alert_type"],
            "total": r["total"],
            "resolved": r["resolved"],
            "resolution_rate": round(r["resolved"] / r["total"] * 100, 1) if r["total"] else 0,
            "avg_resolution_hours": round(r["avg_resolution_hours"], 1) if r["avg_resolution_hours"] else None,
        }
        for r in type_rows
    ]

    return _ok({
        "total": total,
        "resolved": resolved,
        "resolution_rate": round(resolved / total * 100, 1) if total else 0,
        "avg_resolution_hours": round(ov["avg_resolution_hours"], 1) if ov["avg_resolution_hours"] else None,
        "dri_conversion_rate": round((ov["with_order"] or 0) / total * 100, 1) if total else 0,
        "by_type": by_type,
    })


# ── 7. 人力中枢总览 ─────────────────────────────────────────────────────────


@router.get("/hub-overview")
async def get_hub_overview(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """聚合所有 Sprint 1-4 的关键指标，用于总览页。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # -- alerts
    alerts_sql = text("""
        SELECT
            COUNT(*) FILTER (WHERE resolved = FALSE) AS total_unresolved,
            COUNT(*) FILTER (WHERE resolved = FALSE AND severity = 'critical') AS critical,
            CASE WHEN COUNT(*) > 0
                THEN ROUND(COUNT(*) FILTER (WHERE resolved = TRUE)::numeric / COUNT(*) * 100, 1)
                ELSE 0 END AS resolution_rate
        FROM ai_alerts
        WHERE tenant_id = :tid AND is_deleted = FALSE
    """)

    # -- staffing
    staffing_sql = text("""
        SELECT
            COUNT(*) AS total_templates,
            COUNT(*) FILTER (WHERE gap_count > 0) AS gap_stores
        FROM (
            SELECT store_id, COUNT(*) AS gap_count
            FROM ai_alerts
            WHERE tenant_id = :tid AND alert_type = 'peak_gap'
                AND resolved = FALSE AND is_deleted = FALSE
            GROUP BY store_id
        ) sub
    """)

    # -- training
    training_sql = text("""
        SELECT
            COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress,
            COUNT(*) FILTER (WHERE status = 'in_progress' AND expected_end < NOW()) AS overdue,
            CASE WHEN COUNT(*) > 0
                THEN ROUND(COUNT(*) FILTER (WHERE status = 'completed')::numeric / COUNT(*) * 100, 1)
                ELSE 0 END AS completion_rate
        FROM onboarding_paths
        WHERE tenant_id = :tid AND is_deleted = FALSE
    """)

    # -- certification
    cert_sql = text("""
        SELECT
            COUNT(*) AS total,
            CASE WHEN COUNT(*) > 0
                THEN ROUND(COUNT(*) FILTER (WHERE cert_status = 'passed')::numeric / COUNT(*) * 100, 1)
                ELSE 0 END AS pass_rate,
            COUNT(*) FILTER (WHERE expires_at BETWEEN NOW() AND NOW() + INTERVAL '30 days') AS expiring_soon
        FROM position_certifications
        WHERE tenant_id = :tid AND is_deleted = FALSE
    """)

    # -- mentorship
    mentor_sql = text("""
        SELECT
            COUNT(*) FILTER (WHERE status = 'active') AS active,
            COALESCE(AVG(avg_score) FILTER (WHERE status = 'active'), 0) AS avg_score
        FROM mentorship_relations
        WHERE tenant_id = :tid AND is_deleted = FALSE
    """)

    # -- readiness
    readiness_sql = text("""
        SELECT
            COALESCE(AVG(overall_score), 0) AS avg_score,
            COUNT(*) FILTER (WHERE risk_level = 'red') AS red_stores,
            COUNT(*) FILTER (WHERE risk_level = 'green') AS green_stores
        FROM (
            SELECT DISTINCT ON (store_id) store_id, overall_score, risk_level
            FROM store_readiness_scores
            WHERE tenant_id = :tid AND is_deleted = FALSE
            ORDER BY store_id, created_at DESC
        ) latest
    """)

    # -- peak_guard
    peak_sql = text("""
        SELECT
            COUNT(*) FILTER (WHERE event_date >= CURRENT_DATE) AS upcoming,
            COALESCE(AVG(coverage_score), 0) AS avg_coverage,
            COUNT(*) FILTER (WHERE coverage_score < 60) AS low_coverage
        FROM peak_guard_records
        WHERE tenant_id = :tid AND is_deleted = FALSE
            AND event_date >= CURRENT_DATE - 7
    """)

    # -- dri work orders (coaching proxy)
    coaching_sql = text("""
        SELECT
            COUNT(*) FILTER (WHERE created_at >= DATE_TRUNC('week', NOW())) AS this_week,
            CASE WHEN COUNT(*) > 0
                THEN ROUND(COUNT(*) FILTER (WHERE status = 'accepted')::numeric / COUNT(*) * 100, 1)
                ELSE 0 END AS acceptance_rate,
            0 AS avg_lift
        FROM dri_work_orders
        WHERE tenant_id = :tid AND is_deleted = FALSE
    """)

    params = {"tid": tenant_id}
    alerts_r = (await db.execute(alerts_sql, params)).mappings().one()
    staffing_r = (await db.execute(staffing_sql, params)).mappings().one()
    training_r = (await db.execute(training_sql, params)).mappings().one()
    cert_r = (await db.execute(cert_sql, params)).mappings().one()
    mentor_r = (await db.execute(mentor_sql, params)).mappings().one()
    readiness_r = (await db.execute(readiness_sql, params)).mappings().one()
    peak_r = (await db.execute(peak_sql, params)).mappings().one()
    coaching_r = (await db.execute(coaching_sql, params)).mappings().one()

    return _ok({
        "alerts": {
            "total_unresolved": alerts_r["total_unresolved"],
            "critical": alerts_r["critical"],
            "resolution_rate": float(alerts_r["resolution_rate"]),
        },
        "staffing": {
            "total_templates": staffing_r["total_templates"],
            "gap_stores": staffing_r["gap_stores"],
        },
        "training": {
            "in_progress": training_r["in_progress"],
            "overdue": training_r["overdue"],
            "completion_rate": float(training_r["completion_rate"]),
        },
        "certification": {
            "total": cert_r["total"],
            "pass_rate": float(cert_r["pass_rate"]),
            "expiring_soon": cert_r["expiring_soon"],
        },
        "mentorship": {
            "active": mentor_r["active"],
            "avg_score": round(float(mentor_r["avg_score"]), 1),
        },
        "readiness": {
            "avg_score": round(float(readiness_r["avg_score"]), 1),
            "red_stores": readiness_r["red_stores"],
            "green_stores": readiness_r["green_stores"],
        },
        "peak_guard": {
            "upcoming": peak_r["upcoming"],
            "avg_coverage": round(float(peak_r["avg_coverage"]), 1),
            "low_coverage": peak_r["low_coverage"],
        },
        "coaching": {
            "this_week": coaching_r["this_week"],
            "acceptance_rate": float(coaching_r["acceptance_rate"]),
            "avg_lift": float(coaching_r["avg_lift"]),
        },
    })


# ── 8. 周度人力简报 ──────────────────────────────────────────────────────────


@router.get("/weekly-digest")
async def get_weekly_digest(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """本周(Monday-Sunday)的人力简报：新增/解决/关键事件/环比变化。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 本周一和上周一
    today = date.today()
    days_since_monday = today.weekday()
    this_monday = today - timedelta(days=days_since_monday)
    last_monday = this_monday - timedelta(days=7)

    params = {
        "tid": tenant_id,
        "this_monday": this_monday.isoformat(),
        "last_monday": last_monday.isoformat(),
    }

    # 本周 / 上周预警统计
    week_sql = text("""
        SELECT
            COUNT(*) FILTER (WHERE created_at >= :this_monday::date) AS new_this_week,
            COUNT(*) FILTER (WHERE resolved_at >= :this_monday::date AND resolved = TRUE) AS resolved_this_week,
            COUNT(*) FILTER (
                WHERE created_at >= :last_monday::date AND created_at < :this_monday::date
            ) AS new_last_week,
            COUNT(*) FILTER (
                WHERE resolved_at >= :last_monday::date AND resolved_at < :this_monday::date AND resolved = TRUE
            ) AS resolved_last_week
        FROM ai_alerts
        WHERE tenant_id = :tid AND is_deleted = FALSE
    """)
    ws = (await db.execute(week_sql, params)).mappings().one()

    new_this = ws["new_this_week"] or 0
    resolved_this = ws["resolved_this_week"] or 0
    new_last = ws["new_last_week"] or 0

    # 本周 critical 事件
    critical_sql = text("""
        SELECT id, store_id, alert_type, title, created_at
        FROM ai_alerts
        WHERE tenant_id = :tid AND is_deleted = FALSE
            AND severity = 'critical'
            AND created_at >= :this_monday::date
        ORDER BY created_at DESC
        LIMIT 20
    """)
    critical_rows = (await db.execute(critical_sql, params)).mappings().all()

    # 本周风险最高的3个门店
    top_stores_sql = text("""
        SELECT store_id,
            SUM(CASE severity
                WHEN 'critical' THEN 3 WHEN 'warning' THEN 2 ELSE 1
            END) AS risk_score
        FROM ai_alerts
        WHERE tenant_id = :tid AND is_deleted = FALSE
            AND resolved = FALSE
            AND created_at >= :this_monday::date
        GROUP BY store_id
        ORDER BY risk_score DESC
        LIMIT 3
    """)
    top_rows = (await db.execute(top_stores_sql, params)).mappings().all()

    # 本周完成训练
    train_sql = text("""
        SELECT COUNT(*) AS cnt
        FROM onboarding_paths
        WHERE tenant_id = :tid AND is_deleted = FALSE
            AND status = 'completed' AND completed_at >= :this_monday::date
    """)
    train_r = (await db.execute(train_sql, params)).mappings().one()

    # 本周新通过认证
    cert_sql = text("""
        SELECT COUNT(*) AS cnt
        FROM position_certifications
        WHERE tenant_id = :tid AND is_deleted = FALSE
            AND cert_status = 'passed' AND certified_at >= :this_monday::date
    """)
    cert_r = (await db.execute(cert_sql, params)).mappings().one()

    return _ok({
        "week_start": this_monday.isoformat(),
        "new_alerts": new_this,
        "resolved_alerts": resolved_this,
        "net_change": new_this - resolved_this,
        "critical_events": [
            {
                "id": str(r["id"]),
                "store_id": str(r["store_id"]),
                "alert_type": r["alert_type"],
                "title": r["title"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in critical_rows
        ],
        "top_problem_stores": [
            {"store_id": str(r["store_id"]), "risk_score": float(r["risk_score"])}
            for r in top_rows
        ],
        "training_completions": train_r["cnt"],
        "new_certifications": cert_r["cnt"],
        "week_over_week": {
            "new_alerts_change": new_this - new_last,
            "new_alerts_change_pct": (
                round((new_this - new_last) / new_last * 100, 1) if new_last else None
            ),
        },
    })
