"""客户触达SOP旅程 5分钟节拍 Worker

每5分钟扫描所有租户的待执行旅程步骤:
1. 从ACTIVE_TENANT_IDS环境变量获取租户列表
2. 对每个租户执行process_pending_steps()
3. 统计处理结果
"""
from __future__ import annotations

import os

import structlog

from shared.ontology.src.database import get_db_with_tenant

from ..services.customer_journey_service import CustomerJourneyService

logger = structlog.get_logger(__name__)


class CustomerJourneyTickWorker:
    """每5分钟扫描所有租户的待执行旅程步骤

    单租户失败不影响其他租户，错误记录到日志并计入统计。
    """

    async def run(self) -> dict:
        """执行一轮旅程步骤处理

        返回: {tenants_processed, steps_processed, steps_failed, errors}
        """
        tenant_ids_str = os.getenv("ACTIVE_TENANT_IDS", "")
        if not tenant_ids_str:
            logger.warning("customer_journey_tick_skip", reason="no ACTIVE_TENANT_IDS")
            return {
                "tenants_processed": 0,
                "steps_processed": 0,
                "steps_failed": 0,
                "errors": 0,
            }

        tenant_ids = [t.strip() for t in tenant_ids_str.split(",") if t.strip()]
        stats = {
            "tenants_processed": 0,
            "steps_processed": 0,
            "steps_failed": 0,
            "errors": 0,
        }

        for tid in tenant_ids:
            try:
                async for db in get_db_with_tenant(tid):
                    try:
                        svc = CustomerJourneyService(db)
                        result = await svc.process_pending_steps(tid)

                        stats["tenants_processed"] += 1
                        stats["steps_processed"] += result.get("processed", 0)
                        stats["steps_failed"] += result.get("failed", 0)

                        await db.commit()
                    except Exception:
                        logger.exception(
                            "customer_journey_tick_tenant_error",
                            tenant_id=tid,
                        )
                        stats["errors"] += 1
                        await db.rollback()
            except Exception:
                logger.exception(
                    "customer_journey_tick_db_error",
                    tenant_id=tid,
                )
                stats["errors"] += 1

        logger.info("customer_journey_tick_completed", **stats)
        return stats
