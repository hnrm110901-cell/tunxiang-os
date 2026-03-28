"""ETL 手动触发与状态查询 API

端点:
- POST /api/v1/analytics/etl/sync          — 手动触发全量同步
- POST /api/v1/analytics/etl/sync/{tid}    — 触发单租户同步
- GET  /api/v1/analytics/etl/status         — 查看同步状态
- GET  /api/v1/analytics/etl/logs           — 查看最近同步日志
"""
from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ..etl.scheduler import get_etl_scheduler

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/analytics/etl", tags=["etl"])


class TenantSyncRequest(BaseModel):
    start_date: Optional[str] = Field(None, description="开始日期 yyyy-MM-dd")
    end_date: Optional[str] = Field(None, description="结束日期 yyyy-MM-dd")


@router.post("/sync")
async def trigger_full_sync() -> dict[str, Any]:
    logger.info("etl_manual_full_sync_triggered")
    scheduler = get_etl_scheduler()
    try:
        results = await scheduler.trigger_full_sync()
    except (ConnectionError, TimeoutError, RuntimeError) as exc:
        logger.error("etl_manual_full_sync_error", error=str(exc))
        return {"ok": False, "data": None, "error": {"code": "SYNC_FAILED", "message": str(exc)}}
    return {"ok": True, "data": {"sync_results": results, "tenant_count": len(results)}, "error": None}


@router.post("/sync/{tenant_id}")
async def trigger_tenant_sync(tenant_id: str, body: Optional[TenantSyncRequest] = None) -> dict[str, Any]:
    start_date = body.start_date if body else None
    end_date = body.end_date if body else None
    logger.info("etl_manual_tenant_sync_triggered", tenant_id=tenant_id)
    scheduler = get_etl_scheduler()
    try:
        result = await scheduler.trigger_tenant_sync(tenant_id=tenant_id, start_date=start_date, end_date=end_date)
    except (ConnectionError, TimeoutError, RuntimeError) as exc:
        return {"ok": False, "data": None, "error": {"code": "SYNC_FAILED", "message": str(exc)}}
    if not result.get("ok", False):
        return {"ok": False, "data": None, "error": {"code": "TENANT_NOT_FOUND", "message": result.get("error", "未知错误")}}
    return {"ok": True, "data": result, "error": None}


@router.get("/status")
async def get_sync_status() -> dict[str, Any]:
    scheduler = get_etl_scheduler()
    return {"ok": True, "data": scheduler.get_status(), "error": None}


@router.get("/logs")
async def get_sync_logs(
    limit: int = Query(50, ge=1, le=200),
    tenant_id: Optional[str] = Query(None),
) -> dict[str, Any]:
    scheduler = get_etl_scheduler()
    logs = scheduler.get_logs(limit=limit, tenant_id=tenant_id)
    return {"ok": True, "data": {"logs": logs, "total": len(logs)}, "error": None}
