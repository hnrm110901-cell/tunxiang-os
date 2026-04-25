"""舆情爬虫Worker — 定期检测品牌负面口碑激增与评分下降

调度频率：每15分钟（由tx-intel/main.py APScheduler触发）
核心流程：
  1. 遍历所有活跃租户
  2. 为每个租户的每家门店执行负面口碑激增检测
  3. 检测评分下降（近24h vs 近30d，下降>0.3星触发预警）
  4. 结果写入 reputation_alerts 表
"""

from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


class ReputationCrawlerWorker:
    """舆情监控定时Worker

    每15分钟执行一次，遍历所有租户门店，
    检测负面口碑激增和评分下降。
    """

    async def tick(self, db: AsyncSession) -> dict[str, Any]:
        """单次tick：遍历租户+门店，执行舆情检测

        Returns: {tenants_checked, stores_checked, spikes_found, rating_drops_found, errors}
        """
        from ..services.reputation_monitor import ReputationMonitor

        monitor = ReputationMonitor()
        stats: dict[str, Any] = {
            "tenants_checked": 0,
            "stores_checked": 0,
            "spikes_found": 0,
            "rating_drops_found": 0,
            "errors": 0,
        }

        # 查找所有有舆情数据的活跃租户
        tenant_rows = await db.execute(
            text("""
                SELECT DISTINCT tenant_id
                FROM public_opinion_mentions
                WHERE is_deleted = FALSE
                LIMIT 200
            """),
        )
        tenant_ids = [str(r[0]) for r in tenant_rows.fetchall()]

        for tid_str in tenant_ids:
            try:
                import uuid

                tenant_uuid = uuid.UUID(tid_str)

                # 设置RLS上下文
                await db.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": tid_str},
                )

                # 获取该租户下所有门店
                store_rows = await db.execute(
                    text("""
                        SELECT DISTINCT store_id
                        FROM public_opinion_mentions
                        WHERE tenant_id = :tid
                          AND store_id IS NOT NULL
                          AND is_deleted = FALSE
                    """),
                    {"tid": tid_str},
                )
                store_ids = [uuid.UUID(str(r[0])) for r in store_rows.fetchall()]

                # 品牌级别检测（store_id=None）
                targets: list[uuid.UUID | None] = [None]
                targets.extend(store_ids)

                for store_id in targets:
                    try:
                        # 1. 负面口碑激增检测
                        spike_result = await monitor.detect_negative_spike(
                            tenant_id=tenant_uuid,
                            store_id=store_id,
                            db=db,
                            time_window_minutes=60,
                        )
                        if spike_result:
                            stats["spikes_found"] += 1

                        # 2. 评分下降检测
                        drop_result = await monitor.detect_rating_drop(
                            tenant_id=tenant_uuid,
                            store_id=store_id,
                            db=db,
                            drop_threshold=0.3,
                        )
                        if drop_result:
                            stats["rating_drops_found"] += 1

                        if store_id is not None:
                            stats["stores_checked"] += 1

                    except (ValueError, KeyError) as exc:
                        log.warning(
                            "reputation_worker.store_check_failed",
                            tenant_id=tid_str,
                            store_id=str(store_id) if store_id else None,
                            error=str(exc),
                        )
                        stats["errors"] += 1

                stats["tenants_checked"] += 1
                log.info(
                    "reputation_worker.tenant_done",
                    tenant_id=tid_str,
                    stores=len(store_ids),
                )

            except (ValueError, KeyError) as exc:
                log.error(
                    "reputation_worker.tenant_error",
                    tenant_id=tid_str,
                    error=str(exc),
                )
                stats["errors"] += 1

        log.info("reputation_worker.tick_complete", **stats)
        return stats
