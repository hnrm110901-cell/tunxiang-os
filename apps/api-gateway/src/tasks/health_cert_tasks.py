"""
健康证扫描 Celery 任务 — D11 Must-Fix P0

每日 08:00 (Asia/Shanghai) 扫描所有活跃门店健康证到期情况，
聚合结果并通过 IMMessageService 推送店长企微。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

import structlog
from sqlalchemy import select

from src.core.celery_app import celery_app

logger = structlog.get_logger()


@celery_app.task(name="src.tasks.health_cert_tasks.scan_health_certs_daily", bind=True, max_retries=1)
def scan_health_certs_daily(self) -> Dict[str, Any]:
    """每日定时扫描健康证到期（含 30/15/7/1 天分级 + 到期自动停岗）。"""

    async def _run() -> Dict[str, Any]:
        from src.core.database import AsyncSessionLocal
        from src.models.store import Store
        from src.services.health_cert_scan_service import HealthCertScanService

        summary: Dict[str, Any] = {"stores_scanned": 0, "total_alerts": 0, "stores_with_issues": 0}

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Store.id).where(Store.is_active.is_(True)))
            store_ids = [r[0] for r in result.all()]

            for sid in store_ids:
                try:
                    scan = await HealthCertScanService.scan_expiring_certs(db, days_ahead=30, store_id=sid)
                    summary["stores_scanned"] += 1
                    if scan["total"] > 0:
                        summary["stores_with_issues"] += 1
                        summary["total_alerts"] += scan["total"]
                        # 推送企微（复用项目既有 IMMessageService；失败降级为日志）
                        await _push_to_store_manager(sid, HealthCertScanService.build_wechat_summary(scan))
                    await db.commit()
                except Exception as exc:  # noqa: BLE001
                    await db.rollback()
                    logger.warning("health_cert_scan.store_failed", store_id=sid, error=str(exc))

        logger.info("health_cert_scan_daily.done", **summary)
        return summary

    try:
        return asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001
        logger.error("health_cert_scan_daily.failed", error=str(exc))
        return {"error": str(exc)}


async def _push_to_store_manager(store_id: str, text: str) -> None:
    """将健康证预警推送到店长企微；缺失 IM 服务时仅记日志。"""
    try:
        from src.services.im_message_service import IMMessageService  # type: ignore

        await IMMessageService.send_to_store_manager(store_id=store_id, message=text, category="compliance")
    except Exception as exc:  # noqa: BLE001
        logger.info("health_cert_scan.push_fallback_log_only", store_id=store_id, error=str(exc), body=text)
