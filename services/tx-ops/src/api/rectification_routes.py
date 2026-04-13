"""整改指挥中心 API 路由（真实DB版）

数据源：
  compliance_alerts（status IN ('open','acknowledged','in_progress','resolved','dismissed')）
  字段映射：
    id          → task id
    alert_type  → category
    severity    → severity（critical/warning/info → critical/high/medium/low）
    title       → title
    status      → open→pending, in_progress→in_progress, acknowledged→in_progress,
                   resolved→verified, dismissed→rejected
    detail      → {description, assigned_to, assigned_name, region, deadline,
                   evidence_required, evidence_urls, remarks}
    store_id    → store_id
    due_date    → deadline
    resolution_note → remark
    created_at/updated_at

端点:
  GET   /api/v1/ops/rectification/summary                  统计汇总
  GET   /api/v1/ops/rectification/tasks                    任务列表（支持筛选）
  GET   /api/v1/ops/rectification/tasks/{task_id}          任务详情
  POST  /api/v1/ops/rectification/tasks                    从预警创建整改任务
  PATCH /api/v1/ops/rectification/tasks/{task_id}/status   更新状态

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/ops/rectification", tags=["ops-rectification"])
log = structlog.get_logger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  常量与状态映射
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_VALID_STATUSES = {"pending", "in_progress", "submitted", "verified", "rejected", "overdue"}
_VALID_SEVERITIES = {"critical", "high", "medium", "low"}

# DB status → API task status
_STATUS_MAP = {
    "open": "pending",
    "acknowledged": "in_progress",
    "in_progress": "in_progress",
    "resolved": "verified",
    "dismissed": "rejected",
}
# API task status → DB status
_STATUS_RMAP = {
    "pending": "open",
    "in_progress": "in_progress",
    "submitted": "acknowledged",
    "verified": "resolved",
    "rejected": "dismissed",
    "overdue": "open",
}

# DB severity → API severity
_SEVERITY_MAP = {"critical": "critical", "warning": "high", "info": "medium"}
# API severity → DB severity
_SEVERITY_RMAP = {"critical": "critical", "high": "warning", "medium": "info", "low": "info"}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求/响应模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class CreateRectificationTaskRequest(BaseModel):
    alert_id: str = Field(..., description="关联预警ID")
    store_id: str = Field(..., description="门店ID")
    store_name: str = Field(..., description="门店名称")
    title: str = Field(..., max_length=200, description="整改任务标题")
    description: str = Field(..., description="问题描述")
    severity: str = Field("medium", description="critical/high/medium/low")
    category: str = Field(..., description="整改类别: food_safety/hygiene/equipment/service/fire_safety")
    assigned_to: str = Field(..., description="责任人ID")
    assigned_name: str = Field(..., description="责任人姓名")
    deadline: str = Field(..., description="整改截止时间 ISO8601")
    evidence_required: bool = Field(True, description="是否需要整改凭证")
    region: Optional[str] = Field(None, description="区域")


class UpdateStatusRequest(BaseModel):
    status: str = Field(..., description="目标状态: in_progress/submitted/verified/rejected")
    remark: Optional[str] = Field(None, description="备注说明")
    evidence_urls: Optional[List[str]] = Field(None, description="整改凭证图片")
    operator_id: Optional[str] = Field(None, description="操作人ID")
    operator_name: Optional[str] = Field(None, description="操作人姓名")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  内部辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _row_to_task(row: Any) -> Dict[str, Any]:
    """将 compliance_alerts 行转为整改任务对象。"""
    detail: Dict[str, Any] = {}
    if row.detail:
        try:
            detail = row.detail if isinstance(row.detail, dict) else json.loads(row.detail)
        except (ValueError, TypeError):
            detail = {}

    db_status = row.status or "open"
    api_status = _STATUS_MAP.get(db_status, "pending")

    # 判断是否逾期
    deadline_str = detail.get("deadline") or (str(row.due_date) if row.due_date else None)
    if api_status in ("pending", "in_progress") and deadline_str:
        try:
            deadline_dt = datetime.fromisoformat(deadline_str)
            if deadline_dt.tzinfo is None:
                deadline_dt = deadline_dt.replace(tzinfo=timezone.utc)
            if deadline_dt < datetime.now(tz=timezone.utc):
                api_status = "overdue"
        except (ValueError, TypeError):
            pass

    severity_raw = row.severity or "info"
    severity_api = _SEVERITY_MAP.get(severity_raw, "medium")

    return {
        "id": str(row.id),
        "alert_id": detail.get("alert_id", str(row.id)),
        "store_id": str(row.store_id) if row.store_id else detail.get("store_id", ""),
        "store_name": detail.get("store_name", ""),
        "title": row.title or "",
        "description": detail.get("description", row.resolution_note or ""),
        "severity": severity_api,
        "category": detail.get("category", row.alert_type or ""),
        "status": api_status,
        "assigned_to": detail.get("assigned_to", ""),
        "assigned_name": detail.get("assigned_name", ""),
        "region": detail.get("region"),
        "deadline": deadline_str,
        "created_at": str(row.created_at) if row.created_at else None,
        "updated_at": str(row.updated_at) if row.updated_at else None,
        "evidence_required": detail.get("evidence_required", True),
        "evidence_urls": detail.get("evidence_urls", []),
        "remarks": detail.get("remarks", []),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/summary")
async def get_rectification_summary(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """整改任务统计汇总（从 compliance_alerts 聚合）。"""
    log.info("rectification_summary_requested", tenant_id=x_tenant_id)

    try:
        await _set_rls(db, x_tenant_id)

        stats_result = await db.execute(
            text(
                """
                SELECT
                    status,
                    severity,
                    alert_type  AS category,
                    store_id::text,
                    due_date,
                    COUNT(*)    AS cnt
                FROM compliance_alerts
                WHERE source = 'rectification'
                GROUP BY status, severity, alert_type, store_id, due_date
                """
            )
        )
        rows = stats_result.fetchall()

    except SQLAlchemyError as exc:
        log.error("rectification_summary_db_error", error=str(exc), tenant_id=x_tenant_id)
        return {
            "ok": True,
            "data": {
                "total": 0,
                "by_status": {},
                "by_severity": {},
                "by_category": {},
                "overdue_count": 0,
                "completion_rate": 0,
                "avg_resolve_hours": None,
                "top_stores": [],
            },
        }

    status_counts: Dict[str, int] = {}
    severity_counts: Dict[str, int] = {}
    category_counts: Dict[str, int] = {}
    store_counts: Dict[str, int] = {}
    overdue_count = 0
    total = 0

    now = datetime.now(tz=timezone.utc)
    for r in rows:
        cnt = int(r.cnt)
        total += cnt
        api_status = _STATUS_MAP.get(r.status, "pending")
        # check overdue
        if api_status in ("pending", "in_progress") and r.due_date:
            if datetime.combine(r.due_date, datetime.min.time()).replace(tzinfo=timezone.utc) < now:
                api_status = "overdue"
        status_counts[api_status] = status_counts.get(api_status, 0) + cnt
        api_severity = _SEVERITY_MAP.get(r.severity, "medium")
        severity_counts[api_severity] = severity_counts.get(api_severity, 0) + cnt
        category_counts[r.category] = category_counts.get(r.category, 0) + cnt
        if r.store_id:
            store_counts[r.store_id] = store_counts.get(r.store_id, 0) + cnt
        if api_status == "overdue":
            overdue_count += cnt

    completed = status_counts.get("verified", 0)
    completion_rate = round(completed / total * 100, 1) if total > 0 else 0

    top_stores = [
        {"store_id": sid, "count": cnt}
        for sid, cnt in sorted(store_counts.items(), key=lambda x: -x[1])[:5]
    ]

    return {
        "ok": True,
        "data": {
            "total": total,
            "by_status": status_counts,
            "by_severity": severity_counts,
            "by_category": category_counts,
            "overdue_count": overdue_count,
            "completion_rate": completion_rate,
            "avg_resolve_hours": None,
            "top_stores": top_stores,
        },
    }


@router.get("/tasks")
async def list_rectification_tasks(
    status: Optional[str] = Query(None, description="状态筛选"),
    severity: Optional[str] = Query(None, description="严重度筛选"),
    region: Optional[str] = Query(None, description="区域筛选"),
    store_id: Optional[str] = Query(None, description="门店ID筛选"),
    q: Optional[str] = Query(None, description="关键词搜索"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """整改任务列表，支持多条件筛选（从 compliance_alerts 查询）。"""
    if status and status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status 必须是 {_VALID_STATUSES} 之一")
    if severity and severity not in _VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"severity 必须是 {_VALID_SEVERITIES} 之一")

    log.info("rectification_tasks_listed", tenant_id=x_tenant_id,
             status=status, severity=severity, region=region, store_id=store_id)

    try:
        await _set_rls(db, x_tenant_id)

        where_clauses = ["source = 'rectification'"]
        params: Dict[str, Any] = {}

        if severity:
            db_severity = _SEVERITY_RMAP.get(severity, "info")
            where_clauses.append("severity = :sev")
            params["sev"] = db_severity

        if store_id:
            where_clauses.append("store_id = :sid::uuid")
            params["sid"] = store_id

        if q:
            where_clauses.append("(title ILIKE :q OR resolution_note ILIKE :q)")
            params["q"] = f"%{q}%"

        if region:
            where_clauses.append("detail->>'region' = :region")
            params["region"] = region

        # status filter: map API status to DB status(es)
        # overdue is computed at runtime, so we skip DB filter for it and filter in Python
        if status and status != "overdue":
            db_status = _STATUS_RMAP.get(status, status)
            where_clauses.append("status = :db_status")
            params["db_status"] = db_status

        where_sql = " AND ".join(where_clauses)

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM compliance_alerts WHERE {where_sql}"),
            params,
        )
        total = count_result.scalar() or 0

        offset = (page - 1) * size
        rows_result = await db.execute(
            text(
                f"""
                SELECT id, title, alert_type, severity, status, detail,
                       store_id, due_date, resolution_note, created_at, updated_at
                FROM compliance_alerts
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT :lim OFFSET :off
                """
            ),
            {**params, "lim": size, "off": offset},
        )
        rows = rows_result.fetchall()

        tasks = [_row_to_task(r) for r in rows]

        # Post-filter overdue
        if status == "overdue":
            tasks = [t for t in tasks if t["status"] == "overdue"]
            total = len(tasks)

        return {"ok": True, "data": {"items": tasks, "total": total, "page": page, "size": size}}

    except SQLAlchemyError as exc:
        log.error("rectification_tasks_list_db_error", error=str(exc), tenant_id=x_tenant_id)
        return {"ok": True, "data": {"items": [], "total": 0, "page": page, "size": size}}


@router.get("/tasks/{task_id}")
async def get_rectification_task(
    task_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """整改任务详情。"""
    log.info("rectification_task_detail", task_id=task_id, tenant_id=x_tenant_id)

    try:
        await _set_rls(db, x_tenant_id)

        row_result = await db.execute(
            text(
                """
                SELECT id, title, alert_type, severity, status, detail,
                       store_id, due_date, resolution_note, created_at, updated_at
                FROM compliance_alerts
                WHERE id = :tid AND source = 'rectification'
                """
            ),
            {"tid": task_id},
        )
        row = row_result.fetchone()

    except SQLAlchemyError as exc:
        log.error("rectification_task_detail_db_error", error=str(exc), task_id=task_id, tenant_id=x_tenant_id)
        raise HTTPException(status_code=503, detail="数据库暂时不可用")

    if row is None:
        raise HTTPException(status_code=404, detail="整改任务不存在")

    return {"ok": True, "data": _row_to_task(row)}


@router.post("/tasks", status_code=201)
async def create_rectification_task(
    body: CreateRectificationTaskRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """从预警创建整改任务（写入 compliance_alerts，source='rectification'）。"""
    if body.severity not in _VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"severity 必须是 {_VALID_SEVERITIES} 之一")

    now = datetime.now(tz=timezone.utc)
    task_id = str(uuid.uuid4())
    db_severity = _SEVERITY_RMAP.get(body.severity, "info")

    detail_payload = {
        "alert_id": body.alert_id,
        "store_name": body.store_name,
        "description": body.description,
        "category": body.category,
        "assigned_to": body.assigned_to,
        "assigned_name": body.assigned_name,
        "region": body.region,
        "deadline": body.deadline,
        "evidence_required": body.evidence_required,
        "evidence_urls": [],
        "remarks": [],
    }

    try:
        await _set_rls(db, x_tenant_id)

        # Parse store_id safely
        store_id_val = body.store_id if body.store_id else None
        due_date_val: Optional[str] = None
        try:
            due_date_val = datetime.fromisoformat(body.deadline).date().isoformat()
        except (ValueError, TypeError):
            pass

        await db.execute(
            text(
                """
                INSERT INTO compliance_alerts
                    (id, tenant_id, store_id, alert_type, severity, title, detail,
                     status, source, due_date, created_at, updated_at)
                VALUES
                    (:id, :tid::uuid, :sid::uuid, :atype, :sev, :title, :detail::jsonb,
                     'open', 'rectification', :due, :now, :now)
                """
            ),
            {
                "id": task_id,
                "tid": x_tenant_id,
                "sid": store_id_val,
                "atype": body.category,
                "sev": db_severity,
                "title": body.title,
                "detail": json.dumps(detail_payload, ensure_ascii=False),
                "due": due_date_val,
                "now": now,
            },
        )
        await db.commit()

    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("rectification_task_create_db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=503, detail="数据库暂时不可用")

    new_task: Dict[str, Any] = {
        "id": task_id,
        "alert_id": body.alert_id,
        "store_id": body.store_id,
        "store_name": body.store_name,
        "title": body.title,
        "description": body.description,
        "severity": body.severity,
        "category": body.category,
        "status": "pending",
        "assigned_to": body.assigned_to,
        "assigned_name": body.assigned_name,
        "region": body.region,
        "deadline": body.deadline,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "evidence_required": body.evidence_required,
        "evidence_urls": [],
        "remarks": [],
    }

    log.info("rectification_task_created", task_id=task_id,
             store_id=body.store_id, severity=body.severity, tenant_id=x_tenant_id)
    return {"ok": True, "data": new_task}


@router.patch("/tasks/{task_id}/status")
async def update_rectification_status(
    task_id: str,
    body: UpdateStatusRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """更新整改任务状态（更新 compliance_alerts）。"""
    if body.status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status 必须是 {_VALID_STATUSES} 之一")

    log.info("rectification_status_updated", task_id=task_id,
             new_status=body.status, tenant_id=x_tenant_id)

    try:
        await _set_rls(db, x_tenant_id)

        row_result = await db.execute(
            text(
                """
                SELECT id, title, alert_type, severity, status, detail,
                       store_id, due_date, resolution_note, created_at, updated_at
                FROM compliance_alerts
                WHERE id = :tid AND source = 'rectification'
                """
            ),
            {"tid": task_id},
        )
        row = row_result.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="整改任务不存在")

        existing_detail: Dict[str, Any] = {}
        if row.detail:
            try:
                existing_detail = row.detail if isinstance(row.detail, dict) else json.loads(row.detail)
            except (ValueError, TypeError):
                existing_detail = {}

        now = datetime.now(tz=timezone.utc)
        db_status = _STATUS_RMAP.get(body.status, "open")

        if body.evidence_urls is not None:
            existing_detail["evidence_urls"] = body.evidence_urls

        if body.remark:
            remarks = existing_detail.get("remarks", [])
            remarks.append({
                "time": now.isoformat(),
                "operator": body.operator_name or "unknown",
                "content": body.remark,
            })
            existing_detail["remarks"] = remarks

        await db.execute(
            text(
                """
                UPDATE compliance_alerts
                SET status = :status,
                    detail = :detail::jsonb,
                    resolution_note = :note,
                    updated_at = :now
                WHERE id = :tid
                """
            ),
            {
                "status": db_status,
                "detail": json.dumps(existing_detail, ensure_ascii=False),
                "note": body.remark or row.resolution_note,
                "now": now,
                "tid": task_id,
            },
        )
        await db.commit()

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("rectification_status_update_db_error", error=str(exc), task_id=task_id, tenant_id=x_tenant_id)
        raise HTTPException(status_code=503, detail="数据库暂时不可用")

    updated_task = _row_to_task(row)
    updated_task["status"] = body.status
    updated_task["updated_at"] = now.isoformat()
    updated_task["evidence_urls"] = existing_detail.get("evidence_urls", [])
    updated_task["remarks"] = existing_detail.get("remarks", [])

    return {"ok": True, "data": updated_task}
