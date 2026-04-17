"""
HR 健康证到期扫描 API — D11 Must-Fix P0

暴露的端点：
  GET /api/v1/hr/health-certs/expiring?days=30&store_id=...
    返回分级预警结果（只读扫描，不触发推送）
  POST /api/v1/hr/health-certs/trigger-scan
    手动触发一次全量扫描并推送（测试/运维用）
"""

from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..services.health_cert_scan_service import HealthCertScanService

logger = structlog.get_logger()
router = APIRouter()


@router.get("/hr/health-certs/expiring")
async def list_expiring_health_certs(
    days: int = Query(30, ge=1, le=365, description="预警窗口天数"),
    store_id: Optional[str] = Query(None, description="门店ID（不传=全量扫描）"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    扫描 N 天内到期的健康证（含已过期），返回分级预警。
    分级：expired / critical_1d / urgent_7d / warning_15d / notice_30d
    """
    result = await HealthCertScanService.scan_expiring_certs(db, days_ahead=days, store_id=store_id)
    await db.commit()
    return {"ok": True, "data": result}


@router.post("/hr/health-certs/trigger-scan")
async def trigger_health_cert_scan() -> Dict[str, Any]:
    """手动触发健康证扫描 Celery 任务（异步执行）。"""
    from src.tasks.health_cert_tasks import scan_health_certs_daily

    task = scan_health_certs_daily.delay()
    return {"ok": True, "task_id": task.id}
