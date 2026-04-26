"""身份解析定时Worker — S2W5 CDP夜间批量任务

由 APScheduler 调度，每夜遍历所有租户：
1. 解析未匹配的WiFi访问记录
2. 解析未匹配的外部订单导入
3. 输出解析统计日志
"""

from __future__ import annotations

from typing import Any

import structlog
from services.identity_resolver import IdentityResolver
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

_resolver = IdentityResolver()


class IdentityResolutionWorker:
    """夜间批量身份解析任务"""

    async def tick(self, db: AsyncSession) -> dict[str, Any]:
        """
        主入口：遍历所有租户，批量解析未匹配的WiFi访问和外部订单。
        适配 APScheduler 的定时调用。
        """
        # 获取所有活跃租户
        result = await db.execute(
            text("""
                SELECT DISTINCT tenant_id FROM wifi_visit_logs
                WHERE is_deleted = false AND matched_customer_id IS NULL
                UNION
                SELECT DISTINCT tenant_id FROM external_order_imports
                WHERE is_deleted = false AND matched_customer_id IS NULL
            """),
        )
        tenant_ids = [str(r[0]) for r in result.fetchall()]

        stats: dict[str, Any] = {
            "tenants_processed": 0,
            "wifi_resolved": 0,
            "wifi_unmatched": 0,
            "external_resolved": 0,
            "external_unmatched": 0,
        }

        for tid in tenant_ids:
            try:
                # 设置RLS上下文
                await db.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": tid},
                )

                # 解析WiFi访问
                wifi_result = await _resolver.batch_resolve(tid, db, source="wifi")
                stats["wifi_resolved"] += wifi_result["resolved"]
                stats["wifi_unmatched"] += wifi_result["unmatched"]

                # 解析外部订单
                ext_result = await _resolver.batch_resolve(tid, db, source="external")
                stats["external_resolved"] += ext_result["resolved"]
                stats["external_unmatched"] += ext_result["unmatched"]

                stats["tenants_processed"] += 1

                logger.info(
                    "identity_worker.tenant_done",
                    tenant_id=tid,
                    wifi=wifi_result,
                    external=ext_result,
                )
            except (OSError, RuntimeError, ValueError) as exc:
                logger.error(
                    "identity_worker.tenant_error",
                    tenant_id=tid,
                    error=str(exc),
                )
                continue

        logger.info("identity_worker.tick_done", stats=stats)
        return stats
