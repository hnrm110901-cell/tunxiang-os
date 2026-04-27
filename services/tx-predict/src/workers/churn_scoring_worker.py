"""流失评分定时Worker — 每日3am（在RFM 2am后）批量评分所有租户的活跃会员

调度：由tx-predict/main.py APScheduler触发（如tx-predict未独立部署，可在gateway中调度）
"""

import uuid
from typing import Any

import structlog
from sqlalchemy import text

log = structlog.get_logger(__name__)


class ChurnScoringWorker:
    """流失评分批处理Worker"""

    async def tick(self, db: Any) -> dict:
        """单次tick：遍历所有租户，批量评分"""
        from ..services.churn_scorer import ChurnScorer

        scorer = ChurnScorer()
        stats = {"tenants_processed": 0, "total_scored": 0, "total_errors": 0}

        # 获取所有活跃租户
        result = await db.execute(
            text("""
                SELECT DISTINCT tenant_id FROM members
                WHERE is_deleted = FALSE
                LIMIT 100
            """),
        )
        tenant_ids = [row["tenant_id"] for row in result.mappings().all()]

        for tid in tenant_ids:
            try:
                # 设置RLS上下文
                await db.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": str(tid)},
                )
                batch_result = await scorer.batch_score(uuid.UUID(str(tid)), db)
                stats["tenants_processed"] += 1
                stats["total_scored"] += batch_result.get("scored", 0)
                stats["total_errors"] += batch_result.get("errors", 0)
            except (OSError, RuntimeError, ValueError) as exc:
                log.error("churn_worker_tenant_error", tenant_id=str(tid), error=str(exc))

        log.info("churn_scoring_tick_finished", **stats)
        return stats
