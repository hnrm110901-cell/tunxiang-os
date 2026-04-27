"""
经营异常检测 BFF

GET /api/v1/anomaly/today        — 今日异常列表（分级）
GET /api/v1/anomaly/history      — 历史异常记录
POST /api/v1/anomaly/{id}/handle — 标记处理中
POST /api/v1/anomaly/{id}/resolve — 标记已解决
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/anomaly", tags=["anomaly"])


async def _get_db_with_tenant(
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
) -> AsyncSession:
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


@router.get("/today")
async def get_today_anomalies(
    severity: str | None = Query(None, description="critical/warning/info"),
    anomaly_type: str | None = Query(None, description="revenue/inventory/member/equipment"),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    """
    今日经营异常。
    数据来源：store_anomaly 报表 + agent_decision_logs 中的异常检测记录。
    Phase 1 返回骨架结构，待 store_anomaly 服务完整接入后替换。
    """
    try:
        # 从 agent_decision_logs 中提取今日 anomaly 类型决策
        result = await db.execute(
            text("""
            SELECT id::text, agent_id, action, confidence, reasoning,
                   output_action, status, created_at
            FROM agent_decision_logs
            WHERE tenant_id = :tenant_id
              AND decision_type = 'anomaly'
              AND DATE(created_at AT TIME ZONE 'Asia/Shanghai') = CURRENT_DATE
            ORDER BY confidence DESC, created_at DESC
            LIMIT 50
        """),
            {"tenant_id": x_tenant_id},
        )
        rows = result.fetchall()
        anomalies = [
            {
                "id": r.id,
                "agent_id": r.agent_id,
                "description": r.action,
                "analysis": r.reasoning,
                "severity": "critical"
                if r.confidence and float(r.confidence) >= 0.85
                else "warning"
                if r.confidence and float(r.confidence) >= 0.6
                else "info",
                "status": r.status or "pending",
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    except SQLAlchemyError as exc:
        logger.warning("anomaly_today_query_failed", error=str(exc))
        anomalies = []

    severity_counts = {
        "critical": sum(1 for a in anomalies if a["severity"] == "critical"),
        "warning": sum(1 for a in anomalies if a["severity"] == "warning"),
        "info": sum(1 for a in anomalies if a["severity"] == "info"),
    }

    if severity:
        anomalies = [a for a in anomalies if a["severity"] == severity]

    return {
        "ok": True,
        "data": {
            "anomalies": anomalies,
            "summary": {**severity_counts, "total": len(anomalies)},
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


@router.post("/{anomaly_id}/handle")
async def mark_handling(
    anomaly_id: str,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    try:
        await db.execute(
            text("""
            UPDATE agent_decision_logs
            SET status = 'handling', updated_at = NOW()
            WHERE id = :id AND tenant_id = :tenant_id
        """),
            {"id": anomaly_id, "tenant_id": x_tenant_id},
        )
        await db.commit()
        return {"ok": True}
    except SQLAlchemyError as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/{anomaly_id}/resolve")
async def mark_resolved(
    anomaly_id: str,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    try:
        await db.execute(
            text("""
            UPDATE agent_decision_logs
            SET status = 'resolved', updated_at = NOW()
            WHERE id = :id AND tenant_id = :tenant_id
        """),
            {"id": anomaly_id, "tenant_id": x_tenant_id},
        )
        await db.commit()
        return {"ok": True}
    except SQLAlchemyError as exc:
        return {"ok": False, "error": str(exc)}
