"""SOP 15分钟节拍 Worker

每15分钟遍历所有已绑定SOP的门店执行调度：
1. 从ACTIVE_TENANT_IDS环境变量获取租户列表
2. 查sop_store_configs获取每个租户的活跃门店
3. 对每个门店执行scheduler.tick()
4. 统计处理结果
"""

from __future__ import annotations

import os
import uuid

import structlog
from sqlalchemy import select

from shared.ontology.src.database import get_db_with_tenant

from ..models.sop import SOPStoreConfig
from ..services.sop_scheduler_service import SOPSchedulerService

logger = structlog.get_logger(__name__)


class SOPTickWorker:
    """每15分钟遍历所有已绑定SOP的门店执行调度

    单店失败不影响其他门店，错误记录到日志并计入统计。
    """

    async def run(self) -> dict:
        """执行一轮SOP调度

        返回: {stores_processed, tasks_generated, overdue_found, errors}
        """
        tenant_ids_str = os.getenv("ACTIVE_TENANT_IDS", "")
        if not tenant_ids_str:
            logger.warning("sop_tick_skip", reason="no ACTIVE_TENANT_IDS")
            return {"stores_processed": 0, "tasks_generated": 0, "overdue_found": 0, "errors": 0}

        tenant_ids = [t.strip() for t in tenant_ids_str.split(",") if t.strip()]
        stats = {
            "stores_processed": 0,
            "tasks_generated": 0,
            "overdue_found": 0,
            "errors": 0,
        }

        for tid in tenant_ids:
            try:
                async for db in get_db_with_tenant(tid):
                    # 查询该租户所有活跃门店配置
                    stmt = select(SOPStoreConfig).where(
                        SOPStoreConfig.tenant_id == uuid.UUID(tid),
                        SOPStoreConfig.is_active == True,  # noqa: E712
                        SOPStoreConfig.is_deleted == False,  # noqa: E712
                    )
                    result = await db.execute(stmt)
                    configs = list(result.scalars().all())

                    for cfg in configs:
                        try:
                            svc = SOPSchedulerService(db)
                            tick_result = await svc.tick(tid, str(cfg.store_id))

                            stats["stores_processed"] += 1
                            stats["tasks_generated"] += tick_result.get("generated_count", 0)
                            stats["overdue_found"] += tick_result.get("overdue_count", 0)

                            await db.commit()
                        except Exception:
                            logger.exception(
                                "sop_tick_store_error",
                                tenant_id=tid,
                                store_id=str(cfg.store_id),
                            )
                            stats["errors"] += 1
                            await db.rollback()
            except Exception:
                logger.exception("sop_tick_tenant_error", tenant_id=tid)
                stats["errors"] += 1

        logger.info("sop_tick_completed", **stats)
        return stats
