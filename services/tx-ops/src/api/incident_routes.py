"""门店异常事件中心 API 路由

数据源：compliance_alerts 表（RLS 租户隔离）

端点:
  GET   /api/v1/ops/incidents              异常列表
  GET   /api/v1/ops/incidents/summary      异常统计
  POST  /api/v1/ops/incidents              上报异常
  PATCH /api/v1/ops/incidents/{id}/status  更新状态

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

router = APIRouter(prefix="/api/v1/ops/incidents", tags=["ops-incidents"])
log = structlog.get_logger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  常量
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_VALID_TYPES = {"equipment", "food_safety", "customer_complaint", "staff", "supply", "environment", "security", "other"}
_VALID_SEVERITIES = {"critical", "high", "medium", "low"}
# compliance_alerts.status values + route-level aliases
_VALID_STATUSES = {"reported", "confirmed", "handling", "resolved", "closed"}

# Map route status → DB status (compliance_alerts uses open/in_progress/resolved)
_STATUS_TO_DB = {
    "reported": "open",
    "confirmed": "open",
    "handling": "in_progress",
    "resolved": "resolved",
    "closed": "resolved",
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class ReportIncidentRequest(BaseModel):
    store_id: str = Field(..., description="门店ID")
    store_name: str = Field(..., description="门店名称")
    incident_type: str = Field(..., description="异常类型")
    severity: str = Field("medium", description="严重度")
    title: str = Field(..., max_length=200)
    description: str = Field(..., description="详细描述")
    reporter_id: str = Field(..., description="上报人ID")
    reporter_name: str = Field(..., description="上报人姓名")
    evidence_urls: List[str] = Field(default_factory=list, description="证据图片/视频")
    location: Optional[str] = Field(None, description="事发位置: 前厅/后厨/收银台/仓库等")


class UpdateIncidentStatusRequest(BaseModel):
    status: str = Field(..., description="目标状态")
    handler_id: Optional[str] = Field(None, description="处理人ID")
    handler_name: Optional[str] = Field(None, description="处理人姓名")
    remark: Optional[str] = Field(None, description="处理备注")
    resolution: Optional[str] = Field(None, description="解决方案（resolved时必填）")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  依赖注入
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DB 辅助函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _row_to_incident(row: Any) -> Dict[str, Any]:
    """将 compliance_alerts 行映射为 incident 响应格式。"""
    detail: dict = row["detail"] or {}
    db_status = row["status"] or "open"

    # Map DB status back to route status
    route_status = db_status
    if db_status == "open":
        route_status = detail.get("route_status", "reported")
    elif db_status == "in_progress":
        route_status = "handling"

    return {
        "id": str(row["id"]),
        "store_id": str(row["store_id"]) if row["store_id"] else None,
        "store_name": detail.get("store_name", ""),
        "incident_type": row["alert_type"],
        "severity": row["severity"],
        "title": row["title"],
        "description": detail.get("description", ""),
        "status": route_status,
        "reporter_id": detail.get("reporter_id", ""),
        "reporter_name": detail.get("reporter_name", ""),
        "handler_id": detail.get("handler_id"),
        "handler_name": detail.get("handler_name"),
        "evidence_urls": detail.get("evidence_urls", []),
        "location": detail.get("location"),
        "reported_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        "resolved_at": row["resolved_at"].isoformat() if row["resolved_at"] else None,
        "resolution_note": row["resolution_note"],
        "timeline": detail.get("timeline", []),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/summary")
async def get_incidents_summary(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """异常事件统计汇总。"""
    log.info("incidents_summary_requested", tenant_id=x_tenant_id)

    try:
        result = await db.execute(
            text("""
            SELECT
                alert_type,
                severity,
                status,
                store_id::text,
                detail,
                created_at,
                resolved_at
            FROM compliance_alerts
            ORDER BY created_at DESC
        """)
        )
        rows = result.mappings().all()
    except SQLAlchemyError:
        log.exception("incidents_summary_db_error", tenant_id=x_tenant_id)
        rows = []

    by_type: Dict[str, int] = {}
    by_severity: Dict[str, int] = {}
    by_status: Dict[str, int] = {}
    by_store: Dict[str, int] = {}
    unresolved = 0
    critical_unresolved = 0
    resolve_minutes_list: List[int] = []

    for row in rows:
        detail = row["detail"] or {}
        db_status = row["status"] or "open"
        incident_type = row["alert_type"]
        severity = row["severity"]
        store_id = row["store_id"] or "unknown"

        # Map DB status to route status
        if db_status == "in_progress":
            route_status = "handling"
        elif db_status == "open":
            route_status = detail.get("route_status", "reported")
        else:
            route_status = db_status

        by_type[incident_type] = by_type.get(incident_type, 0) + 1
        by_severity[severity] = by_severity.get(severity, 0) + 1
        by_status[route_status] = by_status.get(route_status, 0) + 1
        by_store[store_id] = by_store.get(store_id, 0) + 1

        if route_status not in {"resolved", "closed"}:
            unresolved += 1
            if severity == "critical":
                critical_unresolved += 1

        if row["resolved_at"] and row["created_at"]:
            delta = row["resolved_at"] - row["created_at"]
            resolve_minutes_list.append(int(delta.total_seconds() / 60))

    avg_resolve_minutes = round(sum(resolve_minutes_list) / len(resolve_minutes_list)) if resolve_minutes_list else 0

    top_stores = [{"store_id": sid, "count": cnt} for sid, cnt in sorted(by_store.items(), key=lambda x: -x[1])[:5]]

    return {
        "ok": True,
        "data": {
            "total": len(rows),
            "by_type": by_type,
            "by_severity": by_severity,
            "by_status": by_status,
            "unresolved": unresolved,
            "critical_unresolved": critical_unresolved,
            "top_stores": top_stores,
            "avg_resolve_minutes": avg_resolve_minutes,
        },
    }


@router.get("")
async def list_incidents(
    store_id: Optional[str] = Query(None),
    incident_type: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="关键词搜索"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """异常事件列表，支持筛选。"""
    if incident_type and incident_type not in _VALID_TYPES:
        raise HTTPException(status_code=400, detail=f"incident_type 必须是 {_VALID_TYPES} 之一")
    if severity and severity not in _VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"severity 必须是 {_VALID_SEVERITIES} 之一")
    if status and status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status 必须是 {_VALID_STATUSES} 之一")

    log.info("incidents_listed", tenant_id=x_tenant_id)

    # Build WHERE clauses
    conditions = []
    params: Dict[str, Any] = {}

    if store_id:
        conditions.append("store_id = :store_id")
        params["store_id"] = store_id
    if incident_type:
        conditions.append("alert_type = :incident_type")
        params["incident_type"] = incident_type
    if severity:
        conditions.append("severity = :severity")
        params["severity"] = severity
    if status:
        db_status = _STATUS_TO_DB.get(status, status)
        conditions.append("status = :db_status")
        params["db_status"] = db_status
    if q:
        conditions.append("(title ILIKE :q OR detail->>'description' ILIKE :q)")
        params["q"] = f"%{q}%"

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    try:
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM compliance_alerts {where_clause}"),
            params,
        )
        total = count_result.scalar() or 0

        offset = (page - 1) * size
        rows_result = await db.execute(
            text(f"""
                SELECT id, store_id, alert_type, severity, title,
                       status, detail, created_at, updated_at,
                       resolved_at, resolution_note
                FROM compliance_alerts
                {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {**params, "limit": size, "offset": offset},
        )
        rows = rows_result.mappings().all()
    except SQLAlchemyError:
        log.exception("incidents_list_db_error", tenant_id=x_tenant_id)
        return {"ok": True, "data": {"items": [], "total": 0, "page": page, "size": size}}

    items = [_row_to_incident(row) for row in rows]
    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}


@router.post("", status_code=201)
async def report_incident(
    body: ReportIncidentRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """上报异常事件，写入 compliance_alerts。"""
    if body.incident_type not in _VALID_TYPES:
        raise HTTPException(status_code=400, detail=f"incident_type 必须是 {_VALID_TYPES} 之一")
    if body.severity not in _VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"severity 必须是 {_VALID_SEVERITIES} 之一")

    now = datetime.now(tz=timezone.utc)
    new_id = str(uuid.uuid4())

    detail_payload = {
        "store_name": body.store_name,
        "description": body.description,
        "reporter_id": body.reporter_id,
        "reporter_name": body.reporter_name,
        "handler_id": None,
        "handler_name": None,
        "evidence_urls": body.evidence_urls,
        "location": body.location,
        "route_status": "reported",
        "timeline": [
            {
                "time": now.isoformat(),
                "action": "reported",
                "operator": body.reporter_name,
                "remark": body.description[:100],
            }
        ],
    }

    try:
        await db.execute(
            text("""
            INSERT INTO compliance_alerts
                (id, tenant_id, store_id, alert_type, severity, title,
                 detail, status, source, created_at, updated_at)
            VALUES
                (:id, :tenant_id, :store_id, :alert_type, :severity, :title,
                 :detail::jsonb, 'open', 'manual', :now, :now)
        """),
            {
                "id": new_id,
                "tenant_id": x_tenant_id,
                "store_id": body.store_id,
                "alert_type": body.incident_type,
                "severity": body.severity,
                "title": body.title,
                "detail": __import__("json").dumps(detail_payload, ensure_ascii=False),
                "now": now,
            },
        )
    except SQLAlchemyError:
        log.exception("incident_report_db_error", tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="写入异常事件失败，请稍后重试")

    log.info(
        "incident_reported",
        incident_id=new_id,
        store_id=body.store_id,
        incident_type=body.incident_type,
        severity=body.severity,
        tenant_id=x_tenant_id,
    )

    return {
        "ok": True,
        "data": {
            "id": new_id,
            "store_id": body.store_id,
            "store_name": body.store_name,
            "incident_type": body.incident_type,
            "severity": body.severity,
            "title": body.title,
            "description": body.description,
            "status": "reported",
            "reporter_id": body.reporter_id,
            "reporter_name": body.reporter_name,
            "handler_id": None,
            "handler_name": None,
            "evidence_urls": body.evidence_urls,
            "location": body.location,
            "reported_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "timeline": detail_payload["timeline"],
        },
    }


@router.patch("/{incident_id}/status")
async def update_incident_status(
    incident_id: str,
    body: UpdateIncidentStatusRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """更新异常事件状态。"""
    if body.status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status 必须是 {_VALID_STATUSES} 之一")

    log.info("incident_status_updated", incident_id=incident_id, new_status=body.status, tenant_id=x_tenant_id)

    try:
        row_result = await db.execute(
            text("""
            SELECT id, store_id, alert_type, severity, title,
                   status, detail, created_at, updated_at,
                   resolved_at, resolution_note
            FROM compliance_alerts
            WHERE id = :incident_id
        """),
            {"incident_id": incident_id},
        )
        row = row_result.mappings().first()
    except SQLAlchemyError:
        log.exception("incident_status_fetch_error", incident_id=incident_id)
        raise HTTPException(status_code=500, detail="查询异常事件失败")

    if not row:
        raise HTTPException(status_code=404, detail="异常事件不存在")

    now = datetime.now(tz=timezone.utc)
    detail = dict(row["detail"] or {})
    db_status = _STATUS_TO_DB.get(body.status, body.status)
    resolved_at = now if body.status in {"resolved", "closed"} else row["resolved_at"]

    # Update detail fields
    detail["route_status"] = body.status
    if body.handler_id:
        detail["handler_id"] = body.handler_id
        detail["handler_name"] = body.handler_name
    timeline: list = detail.get("timeline", [])
    timeline.append(
        {
            "time": now.isoformat(),
            "action": body.status,
            "operator": body.handler_name or "system",
            "remark": body.remark or body.resolution or "",
        }
    )
    detail["timeline"] = timeline

    resolution_note = body.resolution or body.remark or row["resolution_note"]

    try:
        await db.execute(
            text("""
            UPDATE compliance_alerts
            SET status = :db_status,
                detail = :detail::jsonb,
                resolution_note = :resolution_note,
                resolved_at = :resolved_at,
                updated_at = :now
            WHERE id = :incident_id
        """),
            {
                "db_status": db_status,
                "detail": __import__("json").dumps(detail, ensure_ascii=False),
                "resolution_note": resolution_note,
                "resolved_at": resolved_at,
                "now": now,
                "incident_id": incident_id,
            },
        )
    except SQLAlchemyError:
        log.exception("incident_status_update_error", incident_id=incident_id)
        raise HTTPException(status_code=500, detail="更新异常事件状态失败")

    return {
        "ok": True,
        "data": {
            "id": incident_id,
            "store_id": str(row["store_id"]) if row["store_id"] else None,
            "store_name": detail.get("store_name", ""),
            "incident_type": row["alert_type"],
            "severity": row["severity"],
            "title": row["title"],
            "description": detail.get("description", ""),
            "status": body.status,
            "reporter_id": detail.get("reporter_id", ""),
            "reporter_name": detail.get("reporter_name", ""),
            "handler_id": detail.get("handler_id"),
            "handler_name": detail.get("handler_name"),
            "evidence_urls": detail.get("evidence_urls", []),
            "location": detail.get("location"),
            "reported_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": now.isoformat(),
            "resolved_at": resolved_at.isoformat() if resolved_at else None,
            "resolution_note": resolution_note,
            "timeline": timeline,
        },
    }
