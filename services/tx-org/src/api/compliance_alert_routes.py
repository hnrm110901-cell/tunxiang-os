"""合规预警管理 API 路由

端点列表：
  GET  /api/v1/compliance/alerts                      预警列表（多维筛选）
  GET  /api/v1/compliance/alerts/export               导出预警报表
  GET  /api/v1/compliance/alerts/{alert_id}           预警详情
  POST /api/v1/compliance/alerts/{alert_id}/acknowledge  确认预警
  POST /api/v1/compliance/alerts/{alert_id}/resolve      解决预警
  GET  /api/v1/compliance/dashboard                   合规总览
  POST /api/v1/compliance/scan                        触发全量扫描

数据源：compliance_alerts + employees + daily_attendance + payroll_records

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/compliance", tags=["compliance-alerts"])


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
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


# ── 请求模型 ──────────────────────────────────────────────────────────────────


class AcknowledgeReq(BaseModel):
    acknowledged_by: str = Field(..., description="确认人ID")
    note: Optional[str] = Field(None, description="确认备注")


class ResolveReq(BaseModel):
    resolved_by: str = Field(..., description="解决人ID")
    resolution_note: str = Field(..., description="解决说明")


class ScanReq(BaseModel):
    scan_type: str = Field(default="all", description="扫描范围: all/documents/attendance/performance")


# ── 端点 ──────────────────────────────────────────────────────────────────────


@router.get("/alerts")
async def list_compliance_alerts(
    request: Request,
    status: Optional[str] = Query(None, description="状态筛选: pending/acknowledged/resolved"),
    alert_type: Optional[str] = Query(None, description="预警类型筛选"),
    severity: Optional[str] = Query(None, description="严重度: critical/high/medium/low"),
    store_id: Optional[str] = Query(None, description="门店筛选"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """预警列表（多维筛选）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    conditions = ["ca.is_deleted = FALSE"]
    params: dict[str, Any] = {"limit": size, "offset": (page - 1) * size}

    if status:
        conditions.append("ca.status = :status")
        params["status"] = status
    if alert_type:
        conditions.append("ca.alert_type = :alert_type")
        params["alert_type"] = alert_type
    if severity:
        conditions.append("ca.severity = :severity")
        params["severity"] = severity
    if store_id:
        conditions.append("ca.store_id = :store_id")
        params["store_id"] = store_id

    where_clause = " AND ".join(conditions)

    count_sql = f"SELECT COUNT(*) FROM compliance_alerts ca WHERE {where_clause}"
    count_result = await db.execute(text(count_sql), params)
    total = count_result.scalar() or 0

    list_sql = f"""
        SELECT
            ca.id::text AS alert_id,
            ca.employee_id::text,
            ca.store_id::text,
            ca.alert_type,
            ca.severity,
            ca.title,
            ca.description,
            ca.status,
            ca.acknowledged_by::text,
            ca.acknowledged_at,
            ca.resolved_by::text,
            ca.resolved_at,
            ca.resolution_note,
            ca.created_at,
            e.emp_name AS employee_name,
            e.phone AS employee_phone
        FROM compliance_alerts ca
        LEFT JOIN employees e ON e.id = ca.employee_id AND e.is_deleted = FALSE
        WHERE {where_clause}
        ORDER BY
            CASE ca.severity
                WHEN 'critical' THEN 1
                WHEN 'high' THEN 2
                WHEN 'medium' THEN 3
                WHEN 'low' THEN 4
            END,
            ca.created_at DESC
        LIMIT :limit OFFSET :offset
    """
    result = await db.execute(text(list_sql), params)
    items = []
    for r in result.fetchall():
        d = dict(r._mapping)
        for key in ("acknowledged_at", "resolved_at", "created_at"):
            if d.get(key):
                d[key] = str(d[key])
        items.append(d)

    log.info("list_compliance_alerts", tenant_id=tenant_id, total=total, page=page)
    return _ok({"items": items, "total": total, "page": page, "size": size})


@router.get("/alerts/export")
async def export_compliance_alerts(
    request: Request,
    status: Optional[str] = Query(None),
    alert_type: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    store_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """导出预警报表（JSON格式，前端转Excel/CSV）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    conditions = ["ca.is_deleted = FALSE"]
    params: dict[str, Any] = {}

    if status:
        conditions.append("ca.status = :status")
        params["status"] = status
    if alert_type:
        conditions.append("ca.alert_type = :alert_type")
        params["alert_type"] = alert_type
    if severity:
        conditions.append("ca.severity = :severity")
        params["severity"] = severity
    if store_id:
        conditions.append("ca.store_id = :store_id")
        params["store_id"] = store_id

    where_clause = " AND ".join(conditions)

    sql = f"""
        SELECT
            ca.id::text AS alert_id,
            ca.alert_type,
            ca.severity,
            ca.title,
            ca.description,
            ca.status,
            ca.resolution_note,
            ca.created_at,
            ca.resolved_at,
            e.emp_name AS employee_name,
            e.phone AS employee_phone,
            e.store_id::text,
            d.name AS department_name
        FROM compliance_alerts ca
        LEFT JOIN employees e ON e.id = ca.employee_id AND e.is_deleted = FALSE
        LEFT JOIN departments d ON d.id = e.department_id AND d.is_active = TRUE
        WHERE {where_clause}
        ORDER BY ca.created_at DESC
        LIMIT 5000
    """
    result = await db.execute(text(sql), params)
    items = []
    for r in result.fetchall():
        d = dict(r._mapping)
        for key in ("created_at", "resolved_at"):
            if d.get(key):
                d[key] = str(d[key])
        items.append(d)

    log.info("export_compliance_alerts", tenant_id=tenant_id, count=len(items))
    return _ok(
        {
            "items": items,
            "total": len(items),
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }
    )


@router.get("/alerts/{alert_id}")
async def get_alert_detail(
    request: Request,
    alert_id: str,
    db: AsyncSession = Depends(get_db),
):
    """预警详情"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    sql = text("""
        SELECT
            ca.id::text AS alert_id,
            ca.employee_id::text,
            ca.store_id::text,
            ca.alert_type,
            ca.severity,
            ca.title,
            ca.description,
            ca.status,
            ca.acknowledged_by::text,
            ca.acknowledged_at,
            ca.acknowledged_note,
            ca.resolved_by::text,
            ca.resolved_at,
            ca.resolution_note,
            ca.created_at,
            ca.updated_at,
            e.emp_name AS employee_name,
            e.phone AS employee_phone,
            e.position AS employee_position,
            e.store_id::text AS employee_store_id,
            d.name AS department_name
        FROM compliance_alerts ca
        LEFT JOIN employees e ON e.id = ca.employee_id AND e.is_deleted = FALSE
        LEFT JOIN departments d ON d.id = e.department_id AND d.is_active = TRUE
        WHERE ca.id = :alert_id AND ca.is_deleted = FALSE
    """)

    result = await db.execute(sql, {"alert_id": alert_id})
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="预警不存在")

    data = dict(row._mapping)
    for key in ("acknowledged_at", "resolved_at", "created_at", "updated_at"):
        if data.get(key):
            data[key] = str(data[key])

    log.info("get_alert_detail", tenant_id=tenant_id, alert_id=alert_id)
    return _ok(data)


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    request: Request,
    alert_id: str,
    req: AcknowledgeReq,
    db: AsyncSession = Depends(get_db),
):
    """确认预警"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    now = datetime.now(timezone.utc)

    result = await db.execute(
        text("""
            UPDATE compliance_alerts
            SET status = 'acknowledged',
                acknowledged_by = :ack_by,
                acknowledged_at = :now,
                acknowledged_note = :note,
                updated_at = :now
            WHERE id = :alert_id AND is_deleted = FALSE AND status = 'pending'
            RETURNING id::text AS alert_id
        """),
        {
            "alert_id": alert_id,
            "ack_by": req.acknowledged_by,
            "note": req.note,
            "now": now,
        },
    )
    row = result.fetchone()
    await db.commit()

    if not row:
        # 可能已确认或不存在
        check = await db.execute(
            text("SELECT status FROM compliance_alerts WHERE id = :alert_id AND is_deleted = FALSE"),
            {"alert_id": alert_id},
        )
        check_row = check.fetchone()
        if not check_row:
            raise HTTPException(status_code=404, detail="预警不存在")
        raise HTTPException(status_code=400, detail=f"预警当前状态为 {check_row._mapping['status']}，无法确认")

    log.info("acknowledge_alert", tenant_id=tenant_id, alert_id=alert_id, by=req.acknowledged_by)
    return _ok({"alert_id": alert_id, "status": "acknowledged", "acknowledged_at": now.isoformat()})


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(
    request: Request,
    alert_id: str,
    req: ResolveReq,
    db: AsyncSession = Depends(get_db),
):
    """解决预警（需resolution_note）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    now = datetime.now(timezone.utc)

    result = await db.execute(
        text("""
            UPDATE compliance_alerts
            SET status = 'resolved',
                resolved_by = :res_by,
                resolved_at = :now,
                resolution_note = :note,
                updated_at = :now
            WHERE id = :alert_id AND is_deleted = FALSE AND status IN ('pending', 'acknowledged')
            RETURNING id::text AS alert_id
        """),
        {
            "alert_id": alert_id,
            "res_by": req.resolved_by,
            "note": req.resolution_note,
            "now": now,
        },
    )
    row = result.fetchone()
    await db.commit()

    if not row:
        check = await db.execute(
            text("SELECT status FROM compliance_alerts WHERE id = :alert_id AND is_deleted = FALSE"),
            {"alert_id": alert_id},
        )
        check_row = check.fetchone()
        if not check_row:
            raise HTTPException(status_code=404, detail="预警不存在")
        raise HTTPException(status_code=400, detail=f"预警当前状态为 {check_row._mapping['status']}，无法解决")

    log.info("resolve_alert", tenant_id=tenant_id, alert_id=alert_id, by=req.resolved_by)
    return _ok({"alert_id": alert_id, "status": "resolved", "resolved_at": now.isoformat()})


@router.get("/dashboard")
async def get_compliance_dashboard(
    request: Request,
    store_id: Optional[str] = Query(None, description="门店筛选"),
    db: AsyncSession = Depends(get_db),
):
    """合规总览（各类预警数量、严重度分布、门店分布）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    store_filter = "AND ca.store_id = :store_id" if store_id else ""
    params: dict[str, Any] = {}
    if store_id:
        params["store_id"] = store_id

    # 总体统计
    overview_sql = text(f"""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE ca.status = 'pending') AS pending_count,
            COUNT(*) FILTER (WHERE ca.status = 'acknowledged') AS acknowledged_count,
            COUNT(*) FILTER (WHERE ca.status = 'resolved') AS resolved_count,
            COUNT(*) FILTER (WHERE ca.severity = 'critical') AS critical_count,
            COUNT(*) FILTER (WHERE ca.severity = 'high') AS high_count,
            COUNT(*) FILTER (WHERE ca.severity = 'medium') AS medium_count,
            COUNT(*) FILTER (WHERE ca.severity = 'low') AS low_count
        FROM compliance_alerts ca
        WHERE ca.is_deleted = FALSE {store_filter}
    """)
    overview_result = await db.execute(text(str(overview_sql)), params)
    overview = dict(overview_result.fetchone()._mapping)
    for key in overview:
        overview[key] = int(overview[key] or 0)

    # 按类型统计
    type_sql = text(f"""
        SELECT
            ca.alert_type,
            COUNT(*) AS count,
            COUNT(*) FILTER (WHERE ca.status = 'pending') AS pending
        FROM compliance_alerts ca
        WHERE ca.is_deleted = FALSE {store_filter}
        GROUP BY ca.alert_type
        ORDER BY count DESC
    """)
    type_result = await db.execute(type_sql, params)
    type_items = []
    for r in type_result.fetchall():
        d = dict(r._mapping)
        d["count"] = int(d.get("count") or 0)
        d["pending"] = int(d.get("pending") or 0)
        type_items.append(d)

    # 按门店统计
    store_sql = text(f"""
        SELECT
            ca.store_id::text,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE ca.status = 'pending') AS pending,
            COUNT(*) FILTER (WHERE ca.severity IN ('critical', 'high')) AS urgent
        FROM compliance_alerts ca
        WHERE ca.is_deleted = FALSE AND ca.store_id IS NOT NULL {store_filter}
        GROUP BY ca.store_id
        ORDER BY urgent DESC, total DESC
    """)
    store_result = await db.execute(store_sql, params)
    store_items = []
    for r in store_result.fetchall():
        d = dict(r._mapping)
        d["total"] = int(d.get("total") or 0)
        d["pending"] = int(d.get("pending") or 0)
        d["urgent"] = int(d.get("urgent") or 0)
        store_items.append(d)

    # 近7天趋势
    trend_sql = text(f"""
        SELECT
            ca.created_at::date AS date,
            COUNT(*) AS new_alerts,
            COUNT(*) FILTER (WHERE ca.status = 'resolved') AS resolved
        FROM compliance_alerts ca
        WHERE ca.is_deleted = FALSE
          AND ca.created_at >= CURRENT_DATE - INTERVAL '7 days'
          {store_filter}
        GROUP BY ca.created_at::date
        ORDER BY date
    """)
    trend_result = await db.execute(trend_sql, params)
    trend_items = []
    for r in trend_result.fetchall():
        d = dict(r._mapping)
        d["date"] = str(d["date"])
        d["new_alerts"] = int(d.get("new_alerts") or 0)
        d["resolved"] = int(d.get("resolved") or 0)
        trend_items.append(d)

    log.info("compliance_dashboard", tenant_id=tenant_id, total=overview.get("total", 0))
    return _ok(
        {
            "overview": {
                "total": overview["total"],
                "by_status": {
                    "pending": overview["pending_count"],
                    "acknowledged": overview["acknowledged_count"],
                    "resolved": overview["resolved_count"],
                },
                "by_severity": {
                    "critical": overview["critical_count"],
                    "high": overview["high_count"],
                    "medium": overview["medium_count"],
                    "low": overview["low_count"],
                },
            },
            "by_type": type_items,
            "by_store": store_items,
            "trend_7d": trend_items,
        }
    )


@router.post("/scan")
async def trigger_compliance_scan(
    request: Request,
    req: ScanReq,
    db: AsyncSession = Depends(get_db),
):
    """触发全量扫描（证照+考勤+绩效）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    valid_types = {"all", "documents", "attendance", "performance"}
    if req.scan_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"scan_type 须为 {sorted(valid_types)} 之一")

    now = datetime.now(timezone.utc)
    created_total = 0

    # 证照扫描
    if req.scan_type in ("all", "documents"):
        doc_sql = text("""
            WITH expiring AS (
                SELECT e.id AS employee_id, e.store_id,
                       'health_cert_expiry' AS alert_type,
                       '健康证' AS doc_name,
                       e.health_cert_expiry AS expiry_date,
                       (e.health_cert_expiry - CURRENT_DATE) AS days_rem
                FROM employees e
                WHERE e.is_deleted = FALSE AND e.status = 'active'
                  AND e.health_cert_expiry IS NOT NULL
                  AND e.health_cert_expiry <= CURRENT_DATE + INTERVAL '30 days'

                UNION ALL

                SELECT e.id, e.store_id,
                       'food_safety_cert_expiry',
                       '食品安全证',
                       e.food_safety_cert_expiry,
                       (e.food_safety_cert_expiry - CURRENT_DATE)
                FROM employees e
                WHERE e.is_deleted = FALSE AND e.status = 'active'
                  AND e.food_safety_cert_expiry IS NOT NULL
                  AND e.food_safety_cert_expiry <= CURRENT_DATE + INTERVAL '30 days'

                UNION ALL

                SELECT e.id, e.store_id,
                       'contract_expiry',
                       '劳动合同',
                       e.contract_end_date,
                       (e.contract_end_date - CURRENT_DATE)
                FROM employees e
                WHERE e.is_deleted = FALSE AND e.status = 'active'
                  AND e.contract_end_date IS NOT NULL
                  AND e.contract_end_date <= CURRENT_DATE + INTERVAL '30 days'
            )
            SELECT * FROM expiring
            WHERE NOT EXISTS (
                SELECT 1 FROM compliance_alerts ca
                WHERE ca.employee_id = expiring.employee_id
                  AND ca.alert_type = expiring.alert_type
                  AND ca.status IN ('pending', 'acknowledged')
            )
        """)
        doc_result = await db.execute(doc_sql)
        for r in doc_result.fetchall():
            d = dict(r._mapping)
            days = int(d["days_rem"]) if d["days_rem"] is not None else 0
            if days < 0:
                sev = "critical"
            elif days <= 7:
                sev = "high"
            elif days <= 15:
                sev = "medium"
            else:
                sev = "low"

            await db.execute(
                text("""
                    INSERT INTO compliance_alerts (
                        id, tenant_id, employee_id, store_id, alert_type, severity,
                        title, description, status, created_at, updated_at, is_deleted
                    ) VALUES (
                        :id, :tid, :emp_id, :store_id, :alert_type, :severity,
                        :title, :desc, 'pending', :now, :now, FALSE
                    )
                """),
                {
                    "id": str(uuid4()),
                    "tid": tenant_id,
                    "emp_id": str(d["employee_id"]),
                    "store_id": str(d["store_id"]) if d.get("store_id") else None,
                    "alert_type": d["alert_type"],
                    "severity": sev,
                    "title": f"{d['doc_name']}{'已过期' if days < 0 else f'将在{days}天后到期'}",
                    "desc": f"到期日期: {d['expiry_date']}, 剩余: {days}天",
                    "now": now,
                },
            )
            created_total += 1

    # 考勤异常扫描
    if req.scan_type in ("all", "attendance"):
        att_sql = text("""
            SELECT
                employee_id,
                store_id,
                COUNT(*) FILTER (WHERE is_absent = TRUE) AS absent_days,
                COUNT(*) FILTER (WHERE is_late = TRUE) AS late_days
            FROM daily_attendance
            WHERE date >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY employee_id, store_id
            HAVING COUNT(*) FILTER (WHERE is_absent = TRUE) >= 3
                OR COUNT(*) FILTER (WHERE is_late = TRUE) >= 5
        """)
        att_result = await db.execute(att_sql)
        for r in att_result.fetchall():
            d = dict(r._mapping)
            absent = int(d.get("absent_days") or 0)
            late = int(d.get("late_days") or 0)
            sev = "high" if absent >= 5 else "medium"

            # 去重
            existing = await db.execute(
                text("""
                    SELECT id FROM compliance_alerts
                    WHERE employee_id = :emp_id AND alert_type = 'attendance_anomaly'
                      AND status IN ('pending', 'acknowledged')
                      AND created_at >= CURRENT_DATE - INTERVAL '7 days'
                    LIMIT 1
                """),
                {"emp_id": str(d["employee_id"])},
            )
            if existing.fetchone():
                continue

            await db.execute(
                text("""
                    INSERT INTO compliance_alerts (
                        id, tenant_id, employee_id, store_id, alert_type, severity,
                        title, description, status, created_at, updated_at, is_deleted
                    ) VALUES (
                        :id, :tid, :emp_id, :store_id, 'attendance_anomaly', :severity,
                        :title, :desc, 'pending', :now, :now, FALSE
                    )
                """),
                {
                    "id": str(uuid4()),
                    "tid": tenant_id,
                    "emp_id": str(d["employee_id"]),
                    "store_id": str(d["store_id"]) if d.get("store_id") else None,
                    "severity": sev,
                    "title": f"考勤异常: 缺勤{absent}天/迟到{late}天（近30天）",
                    "desc": f"缺勤: {absent}天, 迟到: {late}天",
                    "now": now,
                },
            )
            created_total += 1

    # 绩效扫描
    if req.scan_type in ("all", "performance"):
        perf_sql = text("""
            WITH recent AS (
                SELECT
                    employee_id,
                    COUNT(*) AS month_count,
                    AVG(net_salary) AS avg_net
                FROM payroll_records
                WHERE status != 'cancelled'
                  AND (period_year * 12 + period_month) >=
                      (EXTRACT(YEAR FROM CURRENT_DATE)::int * 12
                       + EXTRACT(MONTH FROM CURRENT_DATE)::int - 3)
                GROUP BY employee_id
                HAVING COUNT(*) >= 3
            ),
            overall_avg AS (
                SELECT AVG(avg_net) AS global_avg FROM recent
            )
            SELECT r.employee_id
            FROM recent r, overall_avg oa
            WHERE r.avg_net < oa.global_avg * 0.8
        """)
        perf_result = await db.execute(perf_sql)
        for r in perf_result.fetchall():
            emp_id = str(r._mapping["employee_id"])

            # 去重
            existing = await db.execute(
                text("""
                    SELECT id FROM compliance_alerts
                    WHERE employee_id = :emp_id AND alert_type = 'low_performance'
                      AND status IN ('pending', 'acknowledged')
                      AND created_at >= CURRENT_DATE - INTERVAL '30 days'
                    LIMIT 1
                """),
                {"emp_id": emp_id},
            )
            if existing.fetchone():
                continue

            await db.execute(
                text("""
                    INSERT INTO compliance_alerts (
                        id, tenant_id, employee_id, alert_type, severity,
                        title, description, status, created_at, updated_at, is_deleted
                    ) VALUES (
                        :id, :tid, :emp_id, 'low_performance', 'high',
                        :title, :desc, 'pending', :now, :now, FALSE
                    )
                """),
                {
                    "id": str(uuid4()),
                    "tid": tenant_id,
                    "emp_id": emp_id,
                    "title": "连续低绩效预警",
                    "desc": "近3个月净薪低于全员均值80%",
                    "now": now,
                },
            )
            created_total += 1

    await db.commit()

    log.info("compliance_scan", tenant_id=tenant_id, scan_type=req.scan_type, created=created_total)
    return _ok(
        {
            "scan_type": req.scan_type,
            "created_alerts": created_total,
            "scanned_at": now.isoformat(),
        }
    )
