"""AI 预警中心 API 路由（Human Hub Sprint 1）

端点列表：
  GET    /api/v1/ai-alerts                                预警列表（多维筛选+分页）
  POST   /api/v1/ai-alerts                                创建预警（系统/Agent调用）
  GET    /api/v1/ai-alerts/dashboard                      预警仪表板
  POST   /api/v1/ai-alerts/batch                          批量创建预警
  GET    /api/v1/ai-alerts/store/{store_id}/summary       门店预警摘要
  GET    /api/v1/ai-alerts/{alert_id}                     预警详情
  PUT    /api/v1/ai-alerts/{alert_id}/resolve             处理预警
  PUT    /api/v1/ai-alerts/{alert_id}/dismiss             忽略预警
  POST   /api/v1/ai-alerts/{alert_id}/create-order        预警转工单

数据源：ai_alerts + stores + employees + dri_work_orders

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, List, Optional
from uuid import uuid4

import json
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/ai-alerts", tags=["ai-alerts"])


# ── 常量 ──────────────────────────────────────────────────────────────────

VALID_ALERT_TYPES = {
    "turnover",
    "peak_gap",
    "training_lag",
    "schedule_imbalance",
    "new_store_gap",
}

VALID_SEVERITIES = {"info", "warning", "critical"}

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


def _parse_jsonb(val: Any) -> Any:
    """安全解析 JSONB 字段"""
    if val is None:
        return None
    if isinstance(val, (list, dict)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            return val
    return val


async def _check_duplicate(
    db: AsyncSession,
    tenant_id: str,
    alert_type: str,
    store_id: Optional[str],
    employee_id: Optional[str],
) -> Optional[dict]:
    """检查24小时内是否存在同类型+同门店+同员工的未解决预警，返回已存在的记录或None"""
    conditions = [
        "a.is_deleted = FALSE",
        "a.resolved = FALSE",
        "a.alert_type = :alert_type",
        "a.created_at >= NOW() - INTERVAL '24 hours'",
    ]
    params: dict[str, Any] = {"alert_type": alert_type}

    if store_id:
        conditions.append("a.store_id = :store_id")
        params["store_id"] = store_id
    else:
        conditions.append("a.store_id IS NULL")

    if employee_id:
        conditions.append("a.employee_id = :employee_id")
        params["employee_id"] = employee_id
    else:
        conditions.append("a.employee_id IS NULL")

    where_clause = " AND ".join(conditions)

    result = await db.execute(
        text(f"""
            SELECT
                a.id::text AS alert_id,
                a.alert_type,
                a.store_id::text,
                a.employee_id::text,
                a.severity,
                a.title,
                a.created_at
            FROM ai_alerts a
            WHERE {where_clause}
            ORDER BY a.created_at DESC
            LIMIT 1
        """),
        params,
    )
    row = result.fetchone()
    if not row:
        return None

    d = dict(row._mapping)
    if d.get("created_at"):
        d["created_at"] = str(d["created_at"])
    return d


async def _generate_order_no(db: AsyncSession) -> str:
    """生成工单编号：DRI-YYYYMMDD-0001"""
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"DRI-{today_str}-"

    result = await db.execute(
        text("""
            SELECT MAX(order_no) AS max_no
            FROM dri_work_orders
            WHERE order_no LIKE :prefix || '%'
              AND is_deleted = FALSE
        """),
        {"prefix": prefix},
    )
    row = result.fetchone()
    max_no = row._mapping["max_no"] if row else None

    if max_no:
        seq = int(max_no.split("-")[-1]) + 1
    else:
        seq = 1

    return f"{prefix}{seq:04d}"


# ── 请求模型 ──────────────────────────────────────────────────────────────────


class CreateAlertReq(BaseModel):
    alert_type: str = Field(..., description="预警类型: turnover/peak_gap/training_lag/schedule_imbalance/new_store_gap")
    store_id: Optional[str] = Field(None, description="门店ID")
    employee_id: Optional[str] = Field(None, description="员工ID")
    severity: str = Field(default="warning", description="严重度: info/warning/critical")
    title: str = Field(..., description="预警标题")
    detail: Optional[str] = Field(None, description="预警详情")
    suggestion: Optional[dict] = Field(None, description="建议措施(JSONB)")
    expires_at: Optional[datetime] = Field(None, description="过期时间")


class ResolveAlertReq(BaseModel):
    resolved_by: str = Field(..., description="处理人ID")
    resolution_note: Optional[str] = Field(None, description="处理说明")
    linked_order_id: Optional[str] = Field(None, description="关联工单ID")


class CreateOrderFromAlertReq(BaseModel):
    order_type: str = Field(..., description="工单类型")
    title: str = Field(..., description="工单标题")
    severity: str = Field(default="medium", description="严重度: critical/high/medium/low")
    dri_user_id: Optional[str] = Field(None, description="DRI责任人ID")
    due_date: Optional[date] = Field(None, description="截止日期")


class BatchCreateAlertReq(BaseModel):
    alerts: List[CreateAlertReq] = Field(..., description="预警列表")


# ── 端点 ──────────────────────────────────────────────────────────────────────


@router.get("")
async def list_ai_alerts(
    request: Request,
    store_id: Optional[str] = Query(None, description="门店筛选"),
    alert_type: Optional[str] = Query(None, description="预警类型（逗号分隔多选）"),
    severity: Optional[str] = Query(None, description="严重度: info/warning/critical"),
    resolved: Optional[bool] = Query(False, description="是否已解决，默认false"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """预警列表（多维筛选+分页）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    conditions = ["a.is_deleted = FALSE"]
    params: dict[str, Any] = {"limit": size, "offset": (page - 1) * size}

    if store_id:
        conditions.append("a.store_id = :store_id")
        params["store_id"] = store_id
    if alert_type:
        # 支持逗号分隔多选
        types = [t.strip() for t in alert_type.split(",") if t.strip()]
        if len(types) == 1:
            conditions.append("a.alert_type = :alert_type")
            params["alert_type"] = types[0]
        elif len(types) > 1:
            placeholders = []
            for i, t in enumerate(types):
                key = f"alert_type_{i}"
                placeholders.append(f":{key}")
                params[key] = t
            conditions.append(f"a.alert_type IN ({', '.join(placeholders)})")
    if severity:
        conditions.append("a.severity = :severity")
        params["severity"] = severity
    if resolved is not None:
        conditions.append("a.resolved = :resolved")
        params["resolved"] = resolved

    where_clause = " AND ".join(conditions)

    count_sql = f"SELECT COUNT(*) FROM ai_alerts a WHERE {where_clause}"
    count_result = await db.execute(text(count_sql), params)
    total = count_result.scalar() or 0

    list_sql = f"""
        SELECT
            a.id::text AS alert_id,
            a.alert_type,
            a.store_id::text,
            a.employee_id::text,
            a.severity,
            a.title,
            a.detail,
            a.suggestion,
            a.resolved,
            a.resolved_at,
            a.resolved_by::text,
            a.resolution_note,
            a.linked_order_id::text,
            a.expires_at,
            a.created_at,
            a.updated_at,
            s.name AS store_name,
            e.emp_name AS employee_name
        FROM ai_alerts a
        LEFT JOIN stores s ON s.id = a.store_id AND s.is_deleted = FALSE
        LEFT JOIN employees e ON e.id = a.employee_id AND e.is_deleted = FALSE
        WHERE {where_clause}
        ORDER BY
            CASE a.severity
                WHEN 'critical' THEN 3
                WHEN 'warning' THEN 2
                WHEN 'info' THEN 1
            END DESC,
            a.created_at DESC
        LIMIT :limit OFFSET :offset
    """
    result = await db.execute(text(list_sql), params)
    items = []
    for r in result.fetchall():
        d = dict(r._mapping)
        d["suggestion"] = _parse_jsonb(d.get("suggestion"))
        for key in ("resolved_at", "expires_at", "created_at", "updated_at"):
            if d.get(key):
                d[key] = str(d[key])
        items.append(d)

    log.info("list_ai_alerts", tenant_id=tenant_id, total=total, page=page)
    return _ok({"items": items, "total": total, "page": page, "size": size})


@router.post("")
async def create_ai_alert(
    request: Request,
    req: CreateAlertReq,
    db: AsyncSession = Depends(get_db),
):
    """创建预警（系统/Agent调用）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    if req.alert_type not in VALID_ALERT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"alert_type 须为 {sorted(VALID_ALERT_TYPES)} 之一",
        )
    if req.severity not in VALID_SEVERITIES:
        raise HTTPException(
            status_code=400,
            detail=f"severity 须为 {sorted(VALID_SEVERITIES)} 之一",
        )

    # 去重检查：同类型+同门店+同员工+未解决+24小时内
    existing = await _check_duplicate(
        db, tenant_id, req.alert_type, req.store_id, req.employee_id
    )
    if existing:
        log.info(
            "create_ai_alert_skipped_duplicate",
            tenant_id=tenant_id,
            existing_id=existing["alert_id"],
            alert_type=req.alert_type,
        )
        return _ok({
            "alert_id": existing["alert_id"],
            "duplicate": True,
            "message": "24小时内已存在同类未解决预警，跳过创建",
        })

    now = datetime.now(timezone.utc)
    alert_id = str(uuid4())

    result = await db.execute(
        text("""
            INSERT INTO ai_alerts (
                id, tenant_id, alert_type, store_id, employee_id, severity,
                title, detail, suggestion, resolved, expires_at,
                is_deleted, created_at, updated_at
            ) VALUES (
                :id, :tid, :alert_type, :store_id, :employee_id, :severity,
                :title, :detail, :suggestion, FALSE, :expires_at,
                FALSE, :now, :now
            )
            RETURNING id::text AS alert_id
        """),
        {
            "id": alert_id,
            "tid": tenant_id,
            "alert_type": req.alert_type,
            "store_id": req.store_id,
            "employee_id": req.employee_id,
            "severity": req.severity,
            "title": req.title,
            "detail": req.detail,
            "suggestion": json.dumps(req.suggestion) if req.suggestion else None,
            "expires_at": req.expires_at,
            "now": now,
        },
    )
    row = result.fetchone()
    await db.commit()

    log.info(
        "create_ai_alert",
        tenant_id=tenant_id,
        alert_id=alert_id,
        alert_type=req.alert_type,
        severity=req.severity,
        store_id=req.store_id,
    )
    return _ok({
        "alert_id": row._mapping["alert_id"],
        "duplicate": False,
        "created_at": now.isoformat(),
    })


@router.get("/dashboard")
async def get_ai_alert_dashboard(
    request: Request,
    store_id: Optional[str] = Query(None, description="门店筛选"),
    db: AsyncSession = Depends(get_db),
):
    """预警仪表板"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    store_filter = "AND a.store_id = :store_id" if store_id else ""
    params: dict[str, Any] = {}
    if store_id:
        params["store_id"] = store_id

    # 未解决总数 + 按类型 + 按严重度
    overview_sql = text(f"""
        SELECT
            COUNT(*) FILTER (WHERE a.resolved = FALSE) AS total_unresolved,
            COUNT(*) FILTER (WHERE a.resolved = FALSE AND a.alert_type = 'turnover') AS t_turnover,
            COUNT(*) FILTER (WHERE a.resolved = FALSE AND a.alert_type = 'peak_gap') AS t_peak_gap,
            COUNT(*) FILTER (WHERE a.resolved = FALSE AND a.alert_type = 'training_lag') AS t_training_lag,
            COUNT(*) FILTER (WHERE a.resolved = FALSE AND a.alert_type = 'schedule_imbalance') AS t_schedule_imbalance,
            COUNT(*) FILTER (WHERE a.resolved = FALSE AND a.alert_type = 'new_store_gap') AS t_new_store_gap,
            COUNT(*) FILTER (WHERE a.resolved = FALSE AND a.severity = 'info') AS s_info,
            COUNT(*) FILTER (WHERE a.resolved = FALSE AND a.severity = 'warning') AS s_warning,
            COUNT(*) FILTER (WHERE a.resolved = FALSE AND a.severity = 'critical') AS s_critical
        FROM ai_alerts a
        WHERE a.is_deleted = FALSE {store_filter}
    """)
    overview_result = await db.execute(overview_sql, params)
    ov = dict(overview_result.fetchone()._mapping)
    for key in ov:
        ov[key] = int(ov[key] or 0)

    # 最近5条critical未解决预警
    critical_sql = text(f"""
        SELECT
            a.id::text AS alert_id,
            a.alert_type,
            a.store_id::text,
            a.title,
            a.severity,
            a.created_at,
            s.name AS store_name
        FROM ai_alerts a
        LEFT JOIN stores s ON s.id = a.store_id AND s.is_deleted = FALSE
        WHERE a.is_deleted = FALSE
          AND a.resolved = FALSE
          AND a.severity = 'critical'
          {store_filter}
        ORDER BY a.created_at DESC
        LIMIT 5
    """)
    critical_result = await db.execute(critical_sql, params)
    recent_critical = []
    for r in critical_result.fetchall():
        d = dict(r._mapping)
        if d.get("created_at"):
            d["created_at"] = str(d["created_at"])
        recent_critical.append(d)

    # 近7天新增趋势
    trend_sql = text(f"""
        SELECT
            a.created_at::date AS date,
            COUNT(*) AS count
        FROM ai_alerts a
        WHERE a.is_deleted = FALSE
          AND a.created_at >= CURRENT_DATE - INTERVAL '7 days'
          {store_filter}
        GROUP BY a.created_at::date
        ORDER BY date
    """)
    trend_result = await db.execute(trend_sql, params)
    trend_7d = []
    for r in trend_result.fetchall():
        d = dict(r._mapping)
        d["date"] = str(d["date"])
        d["count"] = int(d["count"] or 0)
        trend_7d.append(d)

    # 近30天解决率
    rate_sql = text(f"""
        SELECT
            COUNT(*) AS total_30d,
            COUNT(*) FILTER (WHERE a.resolved = TRUE) AS resolved_30d
        FROM ai_alerts a
        WHERE a.is_deleted = FALSE
          AND a.created_at >= CURRENT_DATE - INTERVAL '30 days'
          {store_filter}
    """)
    rate_result = await db.execute(rate_sql, params)
    rate_row = dict(rate_result.fetchone()._mapping)
    total_30d = int(rate_row["total_30d"] or 0)
    resolved_30d = int(rate_row["resolved_30d"] or 0)
    resolution_rate = round(resolved_30d / total_30d, 4) if total_30d > 0 else 0.0

    log.info("ai_alert_dashboard", tenant_id=tenant_id, total_unresolved=ov["total_unresolved"])
    return _ok({
        "total_unresolved": ov["total_unresolved"],
        "by_type": {
            "turnover": ov["t_turnover"],
            "peak_gap": ov["t_peak_gap"],
            "training_lag": ov["t_training_lag"],
            "schedule_imbalance": ov["t_schedule_imbalance"],
            "new_store_gap": ov["t_new_store_gap"],
        },
        "by_severity": {
            "info": ov["s_info"],
            "warning": ov["s_warning"],
            "critical": ov["s_critical"],
        },
        "recent_critical": recent_critical,
        "trend_7d": trend_7d,
        "resolution_rate": resolution_rate,
    })


@router.post("/batch")
async def batch_create_ai_alerts(
    request: Request,
    req: BatchCreateAlertReq,
    db: AsyncSession = Depends(get_db),
):
    """批量创建预警（AI Agent scheduler 调用）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    now = datetime.now(timezone.utc)
    created = 0
    skipped_duplicates = 0

    for alert in req.alerts:
        if alert.alert_type not in VALID_ALERT_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"alert_type '{alert.alert_type}' 须为 {sorted(VALID_ALERT_TYPES)} 之一",
            )
        if alert.severity not in VALID_SEVERITIES:
            raise HTTPException(
                status_code=400,
                detail=f"severity '{alert.severity}' 须为 {sorted(VALID_SEVERITIES)} 之一",
            )

        # 去重检查
        existing = await _check_duplicate(
            db, tenant_id, alert.alert_type, alert.store_id, alert.employee_id
        )
        if existing:
            skipped_duplicates += 1
            continue

        alert_id = str(uuid4())
        await db.execute(
            text("""
                INSERT INTO ai_alerts (
                    id, tenant_id, alert_type, store_id, employee_id, severity,
                    title, detail, suggestion, resolved, expires_at,
                    is_deleted, created_at, updated_at
                ) VALUES (
                    :id, :tid, :alert_type, :store_id, :employee_id, :severity,
                    :title, :detail, :suggestion, FALSE, :expires_at,
                    FALSE, :now, :now
                )
            """),
            {
                "id": alert_id,
                "tid": tenant_id,
                "alert_type": alert.alert_type,
                "store_id": alert.store_id,
                "employee_id": alert.employee_id,
                "severity": alert.severity,
                "title": alert.title,
                "detail": alert.detail,
                "suggestion": json.dumps(alert.suggestion) if alert.suggestion else None,
                "expires_at": alert.expires_at,
                "now": now,
            },
        )
        created += 1

    await db.commit()

    log.info(
        "batch_create_ai_alerts",
        tenant_id=tenant_id,
        created=created,
        skipped_duplicates=skipped_duplicates,
    )
    return _ok({
        "created": created,
        "skipped_duplicates": skipped_duplicates,
    })


@router.get("/store/{store_id}/summary")
async def get_store_alert_summary(
    request: Request,
    store_id: str,
    db: AsyncSession = Depends(get_db),
):
    """门店预警摘要（按类型分组，用于门店就绪页面）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    sql = text("""
        WITH ranked AS (
            SELECT
                a.id::text AS alert_id,
                a.alert_type,
                a.severity,
                a.title,
                a.detail,
                a.created_at,
                ROW_NUMBER() OVER (
                    PARTITION BY a.alert_type
                    ORDER BY
                        CASE a.severity
                            WHEN 'critical' THEN 3
                            WHEN 'warning' THEN 2
                            WHEN 'info' THEN 1
                        END DESC,
                        a.created_at DESC
                ) AS rn
            FROM ai_alerts a
            WHERE a.store_id = :store_id
              AND a.is_deleted = FALSE
              AND a.resolved = FALSE
        ),
        type_counts AS (
            SELECT
                a.alert_type,
                COUNT(*) AS count
            FROM ai_alerts a
            WHERE a.store_id = :store_id
              AND a.is_deleted = FALSE
              AND a.resolved = FALSE
            GROUP BY a.alert_type
        )
        SELECT
            tc.alert_type,
            tc.count,
            r.alert_id AS latest_alert_id,
            r.severity AS latest_severity,
            r.title AS latest_title,
            r.detail AS latest_detail,
            r.created_at AS latest_created_at
        FROM type_counts tc
        LEFT JOIN ranked r ON r.alert_type = tc.alert_type AND r.rn = 1
        ORDER BY
            CASE r.severity
                WHEN 'critical' THEN 3
                WHEN 'warning' THEN 2
                WHEN 'info' THEN 1
            END DESC,
            tc.count DESC
    """)

    result = await db.execute(sql, {"store_id": store_id})
    groups = []
    total_unresolved = 0
    for r in result.fetchall():
        d = dict(r._mapping)
        cnt = int(d["count"] or 0)
        total_unresolved += cnt
        if d.get("latest_created_at"):
            d["latest_created_at"] = str(d["latest_created_at"])
        groups.append({
            "alert_type": d["alert_type"],
            "count": cnt,
            "latest": {
                "alert_id": d["latest_alert_id"],
                "severity": d["latest_severity"],
                "title": d["latest_title"],
                "detail": d["latest_detail"],
                "created_at": d["latest_created_at"],
            },
        })

    log.info("store_alert_summary", tenant_id=tenant_id, store_id=store_id, total=total_unresolved)
    return _ok({
        "store_id": store_id,
        "total_unresolved": total_unresolved,
        "by_type": groups,
    })


@router.get("/{alert_id}")
async def get_ai_alert_detail(
    request: Request,
    alert_id: str,
    db: AsyncSession = Depends(get_db),
):
    """预警详情"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    sql = text("""
        SELECT
            a.id::text AS alert_id,
            a.alert_type,
            a.store_id::text,
            a.employee_id::text,
            a.severity,
            a.title,
            a.detail,
            a.suggestion,
            a.resolved,
            a.resolved_at,
            a.resolved_by::text,
            a.resolution_note,
            a.linked_order_id::text,
            a.expires_at,
            a.created_at,
            a.updated_at,
            s.name AS store_name,
            e.emp_name AS employee_name
        FROM ai_alerts a
        LEFT JOIN stores s ON s.id = a.store_id AND s.is_deleted = FALSE
        LEFT JOIN employees e ON e.id = a.employee_id AND e.is_deleted = FALSE
        WHERE a.id = :alert_id AND a.is_deleted = FALSE
    """)

    result = await db.execute(sql, {"alert_id": alert_id})
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="预警不存在")

    data = dict(row._mapping)
    data["suggestion"] = _parse_jsonb(data.get("suggestion"))
    for key in ("resolved_at", "expires_at", "created_at", "updated_at"):
        if data.get(key):
            data[key] = str(data[key])

    # 如果有关联工单，查询工单摘要
    if data.get("linked_order_id"):
        order_sql = text("""
            SELECT
                wo.order_no,
                wo.status
            FROM dri_work_orders wo
            WHERE wo.id = :order_id AND wo.is_deleted = FALSE
        """)
        order_result = await db.execute(order_sql, {"order_id": data["linked_order_id"]})
        order_row = order_result.fetchone()
        if order_row:
            data["linked_order"] = {
                "order_id": data["linked_order_id"],
                "order_no": order_row._mapping["order_no"],
                "status": order_row._mapping["status"],
            }
        else:
            data["linked_order"] = None
    else:
        data["linked_order"] = None

    log.info("get_ai_alert_detail", tenant_id=tenant_id, alert_id=alert_id)
    return _ok(data)


@router.put("/{alert_id}/resolve")
async def resolve_ai_alert(
    request: Request,
    alert_id: str,
    req: ResolveAlertReq,
    db: AsyncSession = Depends(get_db),
):
    """处理预警"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    now = datetime.now(timezone.utc)

    extra_sets = ""
    params: dict[str, Any] = {
        "alert_id": alert_id,
        "resolved_by": req.resolved_by,
        "resolution_note": req.resolution_note,
        "now": now,
    }

    if req.linked_order_id:
        extra_sets = ", linked_order_id = :linked_order_id"
        params["linked_order_id"] = req.linked_order_id

    result = await db.execute(
        text(f"""
            UPDATE ai_alerts
            SET resolved = TRUE,
                resolved_at = :now,
                resolved_by = :resolved_by,
                resolution_note = :resolution_note,
                updated_at = :now
                {extra_sets}
            WHERE id = :alert_id AND is_deleted = FALSE AND resolved = FALSE
            RETURNING id::text AS alert_id
        """),
        params,
    )
    row = result.fetchone()
    await db.commit()

    if not row:
        check = await db.execute(
            text("SELECT resolved FROM ai_alerts WHERE id = :alert_id AND is_deleted = FALSE"),
            {"alert_id": alert_id},
        )
        check_row = check.fetchone()
        if not check_row:
            raise HTTPException(status_code=404, detail="预警不存在")
        raise HTTPException(status_code=400, detail="预警已处理，无法重复操作")

    log.info("resolve_ai_alert", tenant_id=tenant_id, alert_id=alert_id, by=req.resolved_by)
    return _ok({
        "alert_id": alert_id,
        "resolved": True,
        "resolved_at": now.isoformat(),
    })


@router.put("/{alert_id}/dismiss")
async def dismiss_ai_alert(
    request: Request,
    alert_id: str,
    db: AsyncSession = Depends(get_db),
):
    """忽略预警"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    now = datetime.now(timezone.utc)

    result = await db.execute(
        text("""
            UPDATE ai_alerts
            SET resolved = TRUE,
                resolved_at = :now,
                resolution_note = 'dismissed',
                updated_at = :now
            WHERE id = :alert_id AND is_deleted = FALSE AND resolved = FALSE
            RETURNING id::text AS alert_id
        """),
        {"alert_id": alert_id, "now": now},
    )
    row = result.fetchone()
    await db.commit()

    if not row:
        check = await db.execute(
            text("SELECT resolved FROM ai_alerts WHERE id = :alert_id AND is_deleted = FALSE"),
            {"alert_id": alert_id},
        )
        check_row = check.fetchone()
        if not check_row:
            raise HTTPException(status_code=404, detail="预警不存在")
        raise HTTPException(status_code=400, detail="预警已处理，无法重复操作")

    log.info("dismiss_ai_alert", tenant_id=tenant_id, alert_id=alert_id)
    return _ok({
        "alert_id": alert_id,
        "resolved": True,
        "dismissed": True,
        "resolved_at": now.isoformat(),
    })


@router.post("/{alert_id}/create-order")
async def create_order_from_alert(
    request: Request,
    alert_id: str,
    req: CreateOrderFromAlertReq,
    db: AsyncSession = Depends(get_db),
):
    """预警转工单"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 查询预警信息
    alert_result = await db.execute(
        text("""
            SELECT
                a.id::text AS alert_id,
                a.store_id::text,
                a.title AS alert_title,
                a.resolved
            FROM ai_alerts a
            WHERE a.id = :alert_id AND a.is_deleted = FALSE
        """),
        {"alert_id": alert_id},
    )
    alert_row = alert_result.fetchone()
    if not alert_row:
        raise HTTPException(status_code=404, detail="预警不存在")

    alert_data = dict(alert_row._mapping)
    if alert_data["resolved"]:
        raise HTTPException(status_code=400, detail="预警已处理，无法转工单")

    now = datetime.now(timezone.utc)
    order_id = str(uuid4())
    order_no = await _generate_order_no(db)

    # 创建DRI工单
    await db.execute(
        text("""
            INSERT INTO dri_work_orders (
                id, tenant_id, order_no, order_type, store_id, title,
                description, severity, status, dri_user_id,
                due_date, source, source_ref_id,
                is_deleted, created_at, updated_at
            ) VALUES (
                :id, :tid, :order_no, :order_type, :store_id, :title,
                :description, :severity, 'draft', :dri_user_id,
                :due_date, 'ai_alert', :source_ref_id,
                FALSE, :now, :now
            )
        """),
        {
            "id": order_id,
            "tid": tenant_id,
            "order_no": order_no,
            "order_type": req.order_type,
            "store_id": alert_data["store_id"],
            "title": req.title,
            "description": f"由AI预警自动生成：{alert_data['alert_title']}",
            "severity": req.severity,
            "dri_user_id": req.dri_user_id,
            "due_date": req.due_date,
            "source_ref_id": alert_id,
            "now": now,
        },
    )

    # 更新预警关联工单ID
    await db.execute(
        text("""
            UPDATE ai_alerts
            SET linked_order_id = :order_id, updated_at = :now
            WHERE id = :alert_id AND is_deleted = FALSE
        """),
        {"order_id": order_id, "alert_id": alert_id, "now": now},
    )

    await db.commit()

    log.info(
        "create_order_from_alert",
        tenant_id=tenant_id,
        alert_id=alert_id,
        order_id=order_id,
        order_no=order_no,
    )
    return _ok({
        "alert_id": alert_id,
        "order_id": order_id,
        "order_no": order_no,
        "status": "draft",
        "created_at": now.isoformat(),
    })
