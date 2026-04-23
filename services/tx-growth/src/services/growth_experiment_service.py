"""增长实验引擎 — Thompson Sampling自动优化旅程变体

Sprint I: Agent自动试验基础
核心思路：
  - 每个旅程模板可有多个variant（A/B/C...）
  - 每个variant维护 alpha(成功数+1) 和 beta(失败数+1) 参数
  - 选择variant时从Beta(alpha, beta)分布采样，选最高值
  - enrollment完成=成功，exited=失败，更新参数
"""

from __future__ import annotations

import random
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class GrowthExperimentService:
    """基于Thompson Sampling的旅程变体自动选择引擎"""

    async def select_variant(self, template_id: UUID, tenant_id: str, db: AsyncSession) -> dict:
        """Thompson Sampling选择最优variant"""
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        result = await db.execute(
            text("""
            SELECT
                ab_variant,
                COUNT(*) FILTER (WHERE journey_state = 'completed') AS successes,
                COUNT(*) FILTER (WHERE journey_state = 'exited') AS failures,
                COUNT(*) AS total
            FROM growth_journey_enrollments
            WHERE journey_template_id = :tid AND is_deleted = FALSE
              AND ab_variant IS NOT NULL
            GROUP BY ab_variant
        """),
            {"tid": str(template_id)},
        )

        variants = []
        for row in result.fetchall():
            alpha = (row[1] or 0) + 1  # successes + 1 (prior)
            beta_val = (row[2] or 0) + 1  # failures + 1 (prior)
            # Beta分布采样
            sample = random.betavariate(alpha, beta_val)
            variants.append(
                {
                    "variant": row[0],
                    "successes": row[1] or 0,
                    "failures": row[2] or 0,
                    "total": row[3] or 0,
                    "alpha": alpha,
                    "beta": beta_val,
                    "sample": sample,
                    "expected_rate": round(alpha / (alpha + beta_val), 3),
                }
            )

        if not variants:
            return {"selected": "control", "reason": "no_data", "variants": []}

        best = max(variants, key=lambda v: v["sample"])
        logger.info(
            "thompson_sampling_selected",
            template_id=str(template_id),
            selected=best["variant"],
            sample=round(best["sample"], 3),
        )

        return {
            "selected": best["variant"],
            "reason": "thompson_sampling",
            "variants": variants,
        }

    async def should_auto_pause(
        self,
        template_id: UUID,
        min_samples: int,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """检查是否应自动暂停低效variant

        规则：
        - 至少min_samples个样本后才做判断
        - 如果某variant的成功率低于最佳variant的50%，建议暂停
        """
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        result = await db.execute(
            text("""
            SELECT
                ab_variant,
                COUNT(*) FILTER (WHERE journey_state = 'completed') AS successes,
                COUNT(*) AS total
            FROM growth_journey_enrollments
            WHERE journey_template_id = :tid AND is_deleted = FALSE
              AND ab_variant IS NOT NULL
            GROUP BY ab_variant
            HAVING COUNT(*) >= :min_samples
        """),
            {"tid": str(template_id), "min_samples": min_samples},
        )

        variants = []
        for row in result.fetchall():
            total = row[2] or 1
            rate = (row[1] or 0) / total
            variants.append(
                {
                    "variant": row[0],
                    "successes": row[1] or 0,
                    "total": total,
                    "success_rate": round(rate, 3),
                }
            )

        if len(variants) < 2:
            return {
                "action": "continue",
                "reason": "insufficient_variants",
                "variants": variants,
            }

        best_rate = max(v["success_rate"] for v in variants)
        pause_candidates = [v for v in variants if v["success_rate"] < best_rate * 0.5 and v["total"] >= min_samples]

        if pause_candidates:
            return {
                "action": "pause_underperformers",
                "reason": "below_50pct_of_best",
                "best_rate": best_rate,
                "pause_variants": [v["variant"] for v in pause_candidates],
                "variants": variants,
            }

        return {
            "action": "continue",
            "reason": "all_performing_adequately",
            "variants": variants,
        }

    async def get_experiment_summary(self, template_id: UUID, tenant_id: str, db: AsyncSession) -> dict:
        """获取实验摘要"""
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        result = await db.execute(
            text("""
            SELECT
                ab_variant,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE journey_state = 'completed') AS completed,
                COUNT(*) FILTER (WHERE journey_state = 'exited') AS exited,
                COUNT(*) FILTER (WHERE journey_state = 'active') AS active,
                AVG(EXTRACT(EPOCH FROM (COALESCE(completed_at, exited_at) - entered_at))/3600)
                    FILTER (WHERE completed_at IS NOT NULL OR exited_at IS NOT NULL)
                    AS avg_duration_hours
            FROM growth_journey_enrollments
            WHERE journey_template_id = :tid AND is_deleted = FALSE
              AND ab_variant IS NOT NULL
            GROUP BY ab_variant
            ORDER BY ab_variant
        """),
            {"tid": str(template_id)},
        )

        variants = []
        for row in result.fetchall():
            total = row[1] or 1
            variants.append(
                {
                    "variant": row[0],
                    "total": row[1],
                    "completed": row[2],
                    "exited": row[3],
                    "active": row[4],
                    "completion_rate": round((row[2] or 0) / total * 100, 1),
                    "avg_duration_hours": round(row[5], 1) if row[5] else None,
                }
            )

        return {"template_id": str(template_id), "variants": variants}

    async def auto_iterate(self, tenant_id: str, db: AsyncSession, min_samples: int = 30) -> dict:
        """自动迭代 — 扫描所有活跃实验，暂停低效variant，调整流量分配

        逻辑：
        1. 查所有有ab_test_id的活跃模板
        2. 对每个模板检查是否应暂停低效variant
        3. 如发现需暂停的variant，标记其所有pending enrollment为cancelled
        4. 记录决策日志
        """
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        # 查有A/B实验的活跃模板
        templates = await db.execute(
            text("""
            SELECT id, code, name, ab_test_id FROM growth_journey_templates
            WHERE is_deleted = FALSE AND is_active = TRUE AND ab_test_id IS NOT NULL
        """)
        )

        actions_taken = []

        for row in templates.fetchall():
            template_id = row[0]
            template_code = row[1]
            template_name = row[2]

            # 检查是否应暂停
            pause_check = await self.should_auto_pause(template_id, min_samples, tenant_id, db)

            if pause_check["action"] == "pause_underperformers":
                for variant in pause_check["pause_variants"]:
                    # 暂停该variant的所有active enrollment
                    paused = await db.execute(
                        text("""
                        UPDATE growth_journey_enrollments SET
                            journey_state = 'cancelled',
                            exit_reason = 'auto_experiment_pause',
                            exited_at = NOW(),
                            updated_at = NOW()
                        WHERE journey_template_id = :tid
                          AND ab_variant = :variant
                          AND journey_state IN ('eligible', 'active', 'paused')
                          AND is_deleted = FALSE
                        RETURNING id
                    """),
                        {"tid": str(template_id), "variant": variant},
                    )
                    cancelled_count = len(paused.fetchall())

                    action = {
                        "template": template_name,
                        "template_code": template_code,
                        "variant_paused": variant,
                        "enrollments_cancelled": cancelled_count,
                        "best_rate": pause_check["best_rate"],
                        "reason": pause_check["reason"],
                    }
                    actions_taken.append(action)

                    logger.info(
                        "auto_iterate_pause_variant",
                        template=template_code,
                        variant=variant,
                        cancelled=cancelled_count,
                    )

            # 为高效variant增加流量：更新该模板的优先variant
            if pause_check.get("variants"):
                best_variant = max(pause_check["variants"], key=lambda v: v["success_rate"])
                await db.execute(
                    text("""
                    UPDATE growth_journey_templates SET
                        updated_at = NOW()
                    WHERE id = :tid
                """),
                    {"tid": str(template_id)},
                )
                # 记录最优variant到日志
                logger.info(
                    "auto_iterate_best_variant",
                    template=template_code,
                    best=best_variant["variant"],
                    rate=best_variant["success_rate"],
                )

        logger.info("auto_iterate_done", tenant_id=tenant_id, actions=len(actions_taken))
        return {
            "actions_taken": actions_taken,
            "templates_scanned": templates.rowcount if hasattr(templates, "rowcount") else 0,
        }

    async def auto_adjust_journey_params(self, tenant_id: str, db: AsyncSession) -> dict:
        """自动调整旅程参数 — 基于归因结果优化触达时机和渠道

        规则：
        1. 如果某mechanism_type的打开率<10%持续7天，建议切换渠道
        2. 如果某旅程的完成率<5%持续14天，建议暂停
        3. 如果某触达时段的打开率显著高于其他时段，建议调整发送时间
        """
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        adjustments: list[dict] = []

        # 检查低效mechanism
        low_perf = await db.execute(
            text("""
            SELECT
                mechanism_type,
                channel,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE execution_state IN ('opened','clicked','replied')) AS engaged
            FROM growth_touch_executions
            WHERE is_deleted = FALSE
              AND created_at >= NOW() - INTERVAL '7 days'
              AND mechanism_type IS NOT NULL
              AND execution_state NOT IN ('blocked','skipped')
            GROUP BY mechanism_type, channel
            HAVING COUNT(*) >= 20
        """)
        )

        for row in low_perf.fetchall():
            total = row[2] or 1
            engaged = row[3] or 0
            open_rate = engaged / total

            if open_rate < 0.10:
                adjustments.append(
                    {
                        "type": "low_open_rate",
                        "mechanism_type": row[0],
                        "channel": row[1],
                        "open_rate": round(open_rate * 100, 1),
                        "total_touches": total,
                        "recommendation": (
                            f"mechanism={row[0]} channel={row[1]} "
                            f"打开率仅{round(open_rate * 100, 1)}%，建议切换渠道或调整文案"
                        ),
                    }
                )

        # 检查低效旅程
        low_journey = await db.execute(
            text("""
            SELECT
                gjt.code, gjt.name,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE gje.journey_state = 'completed') AS completed
            FROM growth_journey_enrollments gje
            JOIN growth_journey_templates gjt ON gjt.id = gje.journey_template_id
            WHERE gje.is_deleted = FALSE
              AND gje.created_at >= NOW() - INTERVAL '14 days'
            GROUP BY gjt.code, gjt.name
            HAVING COUNT(*) >= 10
        """)
        )

        for row in low_journey.fetchall():
            total = row[2] or 1
            completed = row[3] or 0
            comp_rate = completed / total

            if comp_rate < 0.05:
                adjustments.append(
                    {
                        "type": "low_completion_rate",
                        "journey_code": row[0],
                        "journey_name": row[1],
                        "completion_rate": round(comp_rate * 100, 1),
                        "total_enrollments": total,
                        "recommendation": (
                            f"旅程 {row[1]} 完成率仅{round(comp_rate * 100, 1)}%，建议检查步骤设计或暂停"
                        ),
                    }
                )

        logger.info("auto_adjust_done", tenant_id=tenant_id, adjustments=len(adjustments))
        return {"adjustments": adjustments}
