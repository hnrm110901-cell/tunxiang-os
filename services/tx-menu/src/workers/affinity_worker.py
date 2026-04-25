"""菜品亲和矩阵夜间重算Worker — 每日凌晨4:00按租户+门店重新计算

调度频率：每日04:00（由tx-menu/main.py APScheduler触发）
核心流程：
  1. 查询所有活跃的tenant+store组合
  2. 逐组合调用compute_affinity_matrix重算亲和矩阵
  3. 默认计算last_30d周期，可扩展多周期
"""

from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

log = structlog.get_logger(__name__)


class AffinityWorker:
    """菜品亲和矩阵夜间重算Worker"""

    PERIODS = ["last_7d", "last_30d", "last_90d"]

    async def tick(self, db: Any) -> dict:
        """单次tick：遍历所有活跃tenant+store重算亲和矩阵

        Returns: {
            tenants_processed: int,
            stores_processed: int,
            total_pairs: int,
            errors: int,
        }
        """
        from ..services.dish_affinity import compute_affinity_matrix

        stats = {
            "tenants_processed": 0,
            "stores_processed": 0,
            "total_pairs": 0,
            "errors": 0,
        }

        try:
            # 查询所有有订单数据的tenant+store组合
            result = await db.execute(
                text("""
                    SELECT DISTINCT o.tenant_id, o.store_id
                    FROM orders o
                    WHERE o.status = 'paid'
                      AND o.is_deleted = FALSE
                      AND o.created_at >= NOW() - INTERVAL '90 days'
                    ORDER BY o.tenant_id, o.store_id
                """),
            )
            combos = result.mappings().all()

            seen_tenants: set[str] = set()

            for combo in combos:
                tenant_id = str(combo["tenant_id"])
                store_id = str(combo["store_id"])

                if tenant_id not in seen_tenants:
                    seen_tenants.add(tenant_id)
                    stats["tenants_processed"] += 1

                for period in self.PERIODS:
                    try:
                        # 设置RLS上下文
                        await db.execute(
                            text("SELECT set_config('app.tenant_id', :tid, true)"),
                            {"tid": tenant_id},
                        )

                        result_data = await compute_affinity_matrix(
                            db=db,
                            tenant_id=tenant_id,
                            store_id=store_id,
                            period=period,
                        )
                        stats["total_pairs"] += result_data.get("pairs_computed", 0)

                        log.info(
                            "affinity_worker_store_done",
                            tenant_id=tenant_id,
                            store_id=store_id,
                            period=period,
                            pairs=result_data.get("pairs_computed", 0),
                        )
                    except SQLAlchemyError as exc:
                        stats["errors"] += 1
                        log.error(
                            "affinity_worker_store_error",
                            tenant_id=tenant_id,
                            store_id=store_id,
                            period=period,
                            error=str(exc),
                        )

                stats["stores_processed"] += 1

        except SQLAlchemyError as exc:
            log.error("affinity_worker_global_error", error=str(exc))
            raise

        log.info("affinity_worker_tick_done", **stats)
        return stats
