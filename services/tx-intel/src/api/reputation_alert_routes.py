"""
舆情预警管理 API

GET  /api/v1/intel/reputation/alerts             — 预警列表（分页+筛选）
GET  /api/v1/intel/reputation/alerts/{id}         — 预警详情
POST /api/v1/intel/reputation/alerts/{id}/respond  — 回应预警
POST /api/v1/intel/reputation/alerts/{id}/escalate — 升级预警
POST /api/v1/intel/reputation/alerts/{id}/resolve  — 解决预警
GET  /api/v1/intel/reputation/dashboard           — 舆情仪表盘
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from services.reputation_monitor import ReputationMonitor
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/intel/reputation", tags=["reputation-alerts"])

_monitor = ReputationMonitor()


# ─── 请求模型 ────────────────────────────────────────────────────────


class RespondRequest(BaseModel):
    response_text: str = Field(description="回应内容")


class EscalateRequest(BaseModel):
    escalated_to: str = Field(description="升级目标人UUID")


class ResolveRequest(BaseModel):
    resolution_note: str = Field(description="解决备注")


# ─── 路由 ─────────────────────────────────────────────────────────────


@router.get("/alerts")
async def list_alerts(
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页数量"),
    status: str | None = Query(
        None,
        description="状态筛选: pending/acknowledged/responding/escalated/resolved/dismissed",
    ),
    severity: str | None = Query(None, description="严重级别: low/medium/high/critical"),
    platform: str | None = Query(None, description="平台筛选"),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取舆情预警列表（分页+筛选）"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )

        filters = ""
        params: dict[str, Any] = {
            "tenant_id": x_tenant_id,
            "limit": size,
            "offset": (page - 1) * size,
        }
        if status:
            filters += " AND response_status = :status"
            params["status"] = status
        if severity:
            filters += " AND severity = :severity"
            params["severity"] = severity
        if platform:
            filters += " AND platform = :platform"
            params["platform"] = platform

        # 总数
        count_result = await db.execute(
            text(f"""
                SELECT COUNT(*) FROM reputation_alerts
                WHERE tenant_id = :tenant_id AND is_deleted = false {filters}
            """),
            params,
        )
        total = int(count_result.scalar() or 0)

        # 列表
        result = await db.execute(
            text(f"""
                SELECT id, store_id, platform, alert_type, severity,
                       summary, response_status, response_time_sec,
                       sla_met, assigned_to, created_at, updated_at
                FROM reputation_alerts
                WHERE tenant_id = :tenant_id AND is_deleted = false {filters}
                ORDER BY
                    CASE severity
                        WHEN 'critical' THEN 1
                        WHEN 'high' THEN 2
                        WHEN 'medium' THEN 3
                        WHEN 'low' THEN 4
                    END,
                    created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = result.fetchall()
        items = []
        for row in rows:
            items.append({
                "id": str(row[0]),
                "store_id": str(row[1]) if row[1] else None,
                "platform": row[2],
                "alert_type": row[3],
                "severity": row[4],
                "summary": row[5],
                "response_status": row[6],
                "response_time_sec": row[7],
                "sla_met": row[8],
                "assigned_to": str(row[9]) if row[9] else None,
                "created_at": row[10].isoformat() if row[10] else None,
                "updated_at": row[11].isoformat() if row[11] else None,
            })

        return {
            "ok": True,
            "data": {"items": items, "total": total, "page": page, "size": size},
        }
    except SQLAlchemyError as exc:
        logger.error("reputation_alert.list_failed", error=str(exc))
        return {"ok": False, "error": {"message": "数据库错误", "code": "DB_ERROR"}}


@router.get("/alerts/{alert_id}")
async def get_alert_detail(
    alert_id: str,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取预警详情"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )

        result = await db.execute(
            text("""
                SELECT id, store_id, platform, alert_type, severity,
                       trigger_mention_ids, trigger_data, summary,
                       recommended_actions, response_status, response_text,
                       responded_at, response_time_sec, sla_target_sec, sla_met,
                       assigned_to, escalated_to, escalated_at,
                       resolved_at, resolution_note, created_at, updated_at
                FROM reputation_alerts
                WHERE id = :alert_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = false
            """),
            {"alert_id": alert_id, "tenant_id": x_tenant_id},
        )
        row = result.fetchone()
        if not row:
            return {"ok": False, "error": {"message": "预警不存在", "code": "NOT_FOUND"}}

        data = {
            "id": str(row[0]),
            "store_id": str(row[1]) if row[1] else None,
            "platform": row[2],
            "alert_type": row[3],
            "severity": row[4],
            "trigger_mention_ids": row[5] if isinstance(row[5], list) else [],
            "trigger_data": row[6] if isinstance(row[6], dict) else {},
            "summary": row[7],
            "recommended_actions": row[8] if isinstance(row[8], list) else [],
            "response_status": row[9],
            "response_text": row[10],
            "responded_at": row[11].isoformat() if row[11] else None,
            "response_time_sec": row[12],
            "sla_target_sec": row[13],
            "sla_met": row[14],
            "assigned_to": str(row[15]) if row[15] else None,
            "escalated_to": str(row[16]) if row[16] else None,
            "escalated_at": row[17].isoformat() if row[17] else None,
            "resolved_at": row[18].isoformat() if row[18] else None,
            "resolution_note": row[19],
            "created_at": row[20].isoformat() if row[20] else None,
            "updated_at": row[21].isoformat() if row[21] else None,
        }
        return {"ok": True, "data": data}
    except SQLAlchemyError as exc:
        logger.error("reputation_alert.detail_failed", error=str(exc))
        return {"ok": False, "error": {"message": "数据库错误", "code": "DB_ERROR"}}


@router.post("/alerts/{alert_id}/respond")
async def respond_to_alert(
    alert_id: str,
    body: RespondRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """回应预警"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        result = await _monitor.respond_to_alert(
            tenant_id=uuid.UUID(x_tenant_id),
            alert_id=uuid.UUID(alert_id),
            response_text=body.response_text,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        return {"ok": False, "error": {"message": str(exc), "code": "NOT_FOUND"}}
    except SQLAlchemyError as exc:
        logger.error("reputation_alert.respond_failed", error=str(exc))
        return {"ok": False, "error": {"message": "数据库错误", "code": "DB_ERROR"}}


@router.post("/alerts/{alert_id}/escalate")
async def escalate_alert(
    alert_id: str,
    body: EscalateRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """升级预警"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        result = await _monitor.escalate_alert(
            tenant_id=uuid.UUID(x_tenant_id),
            alert_id=uuid.UUID(alert_id),
            escalated_to=uuid.UUID(body.escalated_to),
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        return {"ok": False, "error": {"message": str(exc), "code": "NOT_FOUND"}}
    except SQLAlchemyError as exc:
        logger.error("reputation_alert.escalate_failed", error=str(exc))
        return {"ok": False, "error": {"message": "数据库错误", "code": "DB_ERROR"}}


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: str,
    body: ResolveRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """解决预警"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        result = await _monitor.resolve_alert(
            tenant_id=uuid.UUID(x_tenant_id),
            alert_id=uuid.UUID(alert_id),
            resolution_note=body.resolution_note,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        return {"ok": False, "error": {"message": str(exc), "code": "NOT_FOUND"}}
    except SQLAlchemyError as exc:
        logger.error("reputation_alert.resolve_failed", error=str(exc))
        return {"ok": False, "error": {"message": "数据库错误", "code": "DB_ERROR"}}


@router.get("/dashboard")
async def reputation_dashboard(
    days: int = Query(30, ge=1, le=365, description="统计天数"),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """舆情仪表盘（预警统计、SLA合规、平均响应时间）"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )

        dashboard = await _monitor.get_alert_dashboard(
            tenant_id=uuid.UUID(x_tenant_id),
            db=db,
            days=days,
        )

        sla_report = await _monitor.get_sla_report(
            tenant_id=uuid.UUID(x_tenant_id),
            db=db,
            days=days,
        )

        return {
            "ok": True,
            "data": {
                "dashboard": dashboard,
                "sla_report": sla_report,
            },
        }
    except SQLAlchemyError as exc:
        logger.error("reputation_alert.dashboard_failed", error=str(exc))
        return {"ok": False, "error": {"message": "数据库错误", "code": "DB_ERROR"}}
