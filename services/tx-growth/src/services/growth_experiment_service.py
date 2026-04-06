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
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class GrowthExperimentService:
    """基于Thompson Sampling的旅程变体自动选择引擎"""

    async def select_variant(
        self, template_id: UUID, tenant_id: str, db: AsyncSession
    ) -> dict:
        """Thompson Sampling选择最优variant"""
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        result = await db.execute(text("""
            SELECT
                ab_variant,
                COUNT(*) FILTER (WHERE journey_state = 'completed') AS successes,
                COUNT(*) FILTER (WHERE journey_state = 'exited') AS failures,
                COUNT(*) AS total
            FROM growth_journey_enrollments
            WHERE journey_template_id = :tid AND is_deleted = FALSE
              AND ab_variant IS NOT NULL
            GROUP BY ab_variant
        """), {"tid": str(template_id)})

        variants = []
        for row in result.fetchall():
            alpha = (row[1] or 0) + 1  # successes + 1 (prior)
            beta_val = (row[2] or 0) + 1   # failures + 1 (prior)
            # Beta分布采样
            sample = random.betavariate(alpha, beta_val)
            variants.append({
                "variant": row[0],
                "successes": row[1] or 0,
                "failures": row[2] or 0,
                "total": row[3] or 0,
                "alpha": alpha,
                "beta": beta_val,
                "sample": sample,
                "expected_rate": round(alpha / (alpha + beta_val), 3),
            })

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

        result = await db.execute(text("""
            SELECT
                ab_variant,
                COUNT(*) FILTER (WHERE journey_state = 'completed') AS successes,
                COUNT(*) AS total
            FROM growth_journey_enrollments
            WHERE journey_template_id = :tid AND is_deleted = FALSE
              AND ab_variant IS NOT NULL
            GROUP BY ab_variant
            HAVING COUNT(*) >= :min_samples
        """), {"tid": str(template_id), "min_samples": min_samples})

        variants = []
        for row in result.fetchall():
            total = row[2] or 1
            rate = (row[1] or 0) / total
            variants.append({
                "variant": row[0],
                "successes": row[1] or 0,
                "total": total,
                "success_rate": round(rate, 3),
            })

        if len(variants) < 2:
            return {
                "action": "continue",
                "reason": "insufficient_variants",
                "variants": variants,
            }

        best_rate = max(v["success_rate"] for v in variants)
        pause_candidates = [
            v for v in variants
            if v["success_rate"] < best_rate * 0.5 and v["total"] >= min_samples
        ]

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

    async def get_experiment_summary(
        self, template_id: UUID, tenant_id: str, db: AsyncSession
    ) -> dict:
        """获取实验摘要"""
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        result = await db.execute(text("""
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
        """), {"tid": str(template_id)})

        variants = []
        for row in result.fetchall():
            total = row[1] or 1
            variants.append({
                "variant": row[0],
                "total": row[1],
                "completed": row[2],
                "exited": row[3],
                "active": row[4],
                "completion_rate": round((row[2] or 0) / total * 100, 1),
                "avg_duration_hours": round(row[5], 1) if row[5] else None,
            })

        return {"template_id": str(template_id), "variants": variants}
