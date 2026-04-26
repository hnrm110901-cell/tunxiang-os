"""Campaign优化Worker — 定期检查运行中AB测试的显著性

调度频率：每小时（由tx-growth/main.py APScheduler触发）
核心流程：
  1. 查找所有status='evaluating'的campaign_optimization_logs
  2. 对每条记录，从AB测试框架拉取最新metrics
  3. 调用CampaignOptimizer.evaluate_round()评估
  4. 显著→自动应用或提交审批; 不显著→继续等待
"""

import uuid
from typing import Any

import structlog
from sqlalchemy import text

log = structlog.get_logger(__name__)


class OptimizationWorker:
    """Campaign自优化定时Worker"""

    async def tick(self, db: Any) -> dict:
        """单次tick：检查所有evaluating状态的优化记录

        Returns: {checked: int, auto_applied: int, pending_approval: int, still_evaluating: int}
        """
        from ..services.campaign_optimizer import CampaignOptimizer

        optimizer = CampaignOptimizer()
        stats = {
            "checked": 0,
            "auto_applied": 0,
            "pending_approval": 0,
            "still_evaluating": 0,
            "errors": 0,
        }

        # 查找所有evaluating状态的优化记录
        result = await db.execute(
            text("""
                SELECT col.id, col.tenant_id, col.campaign_id,
                       col.marketing_task_id, col.ab_test_id,
                       col.optimization_round
                FROM campaign_optimization_logs col
                WHERE col.status = 'evaluating'
                  AND col.is_deleted = FALSE
                ORDER BY col.created_at ASC
                LIMIT 100
            """),
        )
        rows = result.mappings().all()

        for row in rows:
            stats["checked"] += 1
            tenant_id = row["tenant_id"]
            campaign_id = row["campaign_id"]

            try:
                # 设置RLS上下文
                await db.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": str(tenant_id)},
                )

                # 拉取AB测试最新metrics
                metrics = await self._fetch_ab_metrics(db, tenant_id, campaign_id, row.get("ab_test_id"))

                if not metrics:
                    stats["still_evaluating"] += 1
                    continue

                # 评估
                eval_result = await optimizer.evaluate_round(
                    uuid.UUID(str(tenant_id)),
                    uuid.UUID(str(campaign_id)),
                    db,
                    variant_a_metrics=metrics["variant_a"],
                    variant_b_metrics=metrics["variant_b"],
                )

                status = eval_result["status"]
                if status == "auto_applied":
                    stats["auto_applied"] += 1
                    # 自动应用优化结果
                    await optimizer.apply_optimization(
                        uuid.UUID(str(tenant_id)),
                        uuid.UUID(str(eval_result["optimization_id"])),
                        db,
                    )
                elif status == "pending_approval":
                    stats["pending_approval"] += 1
                else:
                    stats["still_evaluating"] += 1

            except (OSError, RuntimeError, ValueError) as exc:
                stats["errors"] += 1
                log.error(
                    "optimization_tick_error",
                    campaign_id=str(campaign_id),
                    error=str(exc),
                    exc_info=True,
                )

        log.info("optimization_tick_finished", **stats)
        return stats

    async def _fetch_ab_metrics(
        self,
        db: Any,
        tenant_id: Any,
        campaign_id: Any,
        ab_test_id: Any,
    ) -> dict | None:
        """从营销任务执行记录中汇总AB变体的metrics

        Returns: {"variant_a": {...}, "variant_b": {...}} or None if no data
        """
        # 从marketing_task_executions和coupon_send_logs汇总
        result = await db.execute(
            text("""
                WITH task_metrics AS (
                    SELECT
                        COALESCE(mt.content->>'ab_variant', 'a') AS variant,
                        COUNT(*) AS send_count,
                        COUNT(*) FILTER (WHERE mte.status = 'delivered') AS delivered_count,
                        COUNT(*) FILTER (WHERE mte.status = 'opened') AS opened_count,
                        COUNT(*) FILTER (WHERE mte.status = 'clicked') AS clicked_count,
                        COUNT(*) FILTER (WHERE mte.status = 'converted') AS converted_count,
                        COALESCE(SUM(mte.revenue_fen), 0) AS revenue_fen
                    FROM marketing_tasks mt
                    LEFT JOIN marketing_task_executions mte ON mte.marketing_task_id = mt.id
                    WHERE mt.tenant_id = :tenant_id
                      AND (mt.campaign_id = :campaign_id OR mt.id = :campaign_id)
                      AND mt.is_deleted = FALSE
                    GROUP BY COALESCE(mt.content->>'ab_variant', 'a')
                )
                SELECT * FROM task_metrics
            """),
            {"tenant_id": str(tenant_id), "campaign_id": str(campaign_id)},
        )
        rows = {str(r["variant"]): dict(r) for r in result.mappings().all()}

        if not rows:
            return None

        def _build_metrics(row: dict | None) -> dict:
            if not row:
                return {"send_count": 0, "conversion_rate": 0.0, "revenue_fen": 0}
            sc = row.get("send_count", 0) or 0
            cc = row.get("converted_count", 0) or 0
            return {
                "send_count": sc,
                "delivered_count": row.get("delivered_count", 0) or 0,
                "opened_count": row.get("opened_count", 0) or 0,
                "clicked_count": row.get("clicked_count", 0) or 0,
                "converted_count": cc,
                "revenue_fen": row.get("revenue_fen", 0) or 0,
                "open_rate": (row.get("opened_count", 0) or 0) / max(sc, 1),
                "click_rate": (row.get("clicked_count", 0) or 0) / max(sc, 1),
                "conversion_rate": cc / max(sc, 1),
                "roi": (row.get("revenue_fen", 0) or 0) / max(sc, 1),
            }

        return {
            "variant_a": _build_metrics(rows.get("a")),
            "variant_b": _build_metrics(rows.get("b")),
        }
