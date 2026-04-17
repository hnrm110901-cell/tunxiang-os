"""
劳动合同扫描 Celery 任务 — D9 Must-Fix P0

每日 08:10 (Asia/Shanghai) 扫描所有活跃门店劳动合同到期情况（60/30/15 天分级），
聚合后推送店长 / HR 企微。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

import structlog
from sqlalchemy import select

from src.core.celery_app import celery_app

logger = structlog.get_logger()


@celery_app.task(name="src.tasks.labor_contract_tasks.scan_labor_contracts_daily", bind=True, max_retries=1)
def scan_labor_contracts_daily(self) -> Dict[str, Any]:
    """每日定时扫描劳动合同到期（60/30/15 天分级 + 状态回写）。"""

    async def _run() -> Dict[str, Any]:
        from src.core.database import AsyncSessionLocal
        from src.models.store import Store
        from src.services.labor_contract_alert_service import LaborContractAlertService

        summary: Dict[str, Any] = {"stores_scanned": 0, "total_alerts": 0, "stores_with_issues": 0}

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Store.id).where(Store.is_active.is_(True)))
            store_ids = [r[0] for r in result.all()]

            for sid in store_ids:
                try:
                    scan = await LaborContractAlertService.scan_expiring_contracts(
                        db, days_ahead=60, store_id=sid
                    )
                    summary["stores_scanned"] += 1
                    if scan["total"] > 0:
                        summary["stores_with_issues"] += 1
                        summary["total_alerts"] += scan["total"]
                        await _push_to_store_manager(
                            sid, LaborContractAlertService.build_wechat_summary(scan)
                        )
                    await db.commit()
                except Exception as exc:  # noqa: BLE001
                    await db.rollback()
                    logger.warning("labor_contract_scan.store_failed", store_id=sid, error=str(exc))

        logger.info("labor_contract_scan_daily.done", **summary)
        return summary

    try:
        return asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001
        logger.error("labor_contract_scan_daily.failed", error=str(exc))
        return {"error": str(exc)}


async def _push_to_store_manager(store_id: str, text: str) -> None:
    """推送劳动合同预警到店长企微；失败降级日志。"""
    try:
        from src.services.im_message_service import IMMessageService  # type: ignore

        await IMMessageService.send_to_store_manager(store_id=store_id, message=text, category="compliance")
    except Exception as exc:  # noqa: BLE001
        logger.info("labor_contract_scan.push_fallback_log_only", store_id=store_id, error=str(exc), body=text)
