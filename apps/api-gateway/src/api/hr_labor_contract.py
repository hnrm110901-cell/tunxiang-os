"""
HR 劳动合同到期预警 API — D9 Must-Fix P0

暴露的端点：
  GET /api/v1/hr/contracts/expiring?days=60&store_id=...
  POST /api/v1/hr/contracts/trigger-scan

（注：hr_performance.py 里历史上有同名 /hr/contracts/expiring 端点用于续签管理；
 本模块聚焦合规扫描，提供分级预警与自动状态回写。前缀使用 /hr/labor-contracts 避免冲突。）
"""

from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..services.labor_contract_alert_service import LaborContractAlertService

logger = structlog.get_logger()
router = APIRouter()


@router.get("/hr/labor-contracts/expiring")
async def list_expiring_labor_contracts(
    days: int = Query(60, ge=1, le=365, description="预警窗口天数"),
    store_id: Optional[str] = Query(None, description="门店ID（不传=全量扫描）"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    扫描 N 天内到期的劳动合同（含已过期），返回分级预警。
    分级：expired / urgent_15d / warning_30d / notice_60d
    """
    result = await LaborContractAlertService.scan_expiring_contracts(db, days_ahead=days, store_id=store_id)
    await db.commit()
    return {"ok": True, "data": result}


@router.post("/hr/labor-contracts/trigger-scan")
async def trigger_labor_contract_scan() -> Dict[str, Any]:
    """手动触发劳动合同扫描 Celery 任务。"""
    from src.tasks.labor_contract_tasks import scan_labor_contracts_daily

    task = scan_labor_contracts_daily.delay()
    return {"ok": True, "task_id": task.id}
