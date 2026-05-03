"""身份解析定时Worker — S2W5 CDP夜间批量任务 + MU-1 UnionID补全

由 APScheduler 调度，每夜遍历所有租户：
1. 解析未匹配的WiFi访问记录
2. 解析未匹配的外部订单导入
3. 补全存量会员 UnionID（每6小时自动检查新增未关联UnionID会员）
4. 输出解析统计日志
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
    """夜间批量身份解析任务 + UnionID定时补全"""

    async def tick(self, db: AsyncSession) -> dict[str, Any]:
        """
        主入口：遍历所有租户，批量解析未匹配的WiFi访问和外部订单，
        以及补全存量会员UnionID。

        适配 APScheduler 的定时调用（每6小时执行一次）。
        """
        # 获取所有有未处理数据的活跃租户
        result = await db.execute(
            text("""
                SELECT DISTINCT tenant_id FROM wifi_visit_logs
                WHERE is_deleted = false AND matched_customer_id IS NULL
                UNION
                SELECT DISTINCT tenant_id FROM external_order_imports
                WHERE is_deleted = false AND matched_customer_id IS NULL
                UNION
                SELECT DISTINCT tenant_id FROM customers
                WHERE is_deleted = false
                  AND wechat_openid IS NOT NULL
                  AND wechat_unionid IS NULL
            """),
        )
        tenant_ids = [str(r[0]) for r in result.fetchall()]

        stats: dict[str, Any] = {
            "tenants_processed": 0,
            "wifi_resolved": 0,
            "wifi_unmatched": 0,
            "external_resolved": 0,
            "external_unmatched": 0,
            "unionid_backfill_total": 0,
            "unionid_backfill_succeeded": 0,
            "unionid_backfill_failed": 0,
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

                # UnionID 批量补全（每6小时自动执行一次）
                backfill_report = await _resolver.backfill_union_id(tid, db)
                stats["unionid_backfill_total"] += backfill_report.total
                stats["unionid_backfill_succeeded"] += backfill_report.succeeded
                stats["unionid_backfill_failed"] += backfill_report.failed

                stats["tenants_processed"] += 1

                logger.info(
                    "identity_worker.tenant_done",
                    tenant_id=tid,
                    wifi=wifi_result,
                    external=ext_result,
                    unionid_backfill={
                        "total": backfill_report.total,
                        "succeeded": backfill_report.succeeded,
                        "failed": backfill_report.failed,
                    },
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
