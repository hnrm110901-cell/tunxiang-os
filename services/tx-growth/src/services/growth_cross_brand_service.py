"""跨品牌增长服务 — 客户去重+统一触达历史+交叉推荐

V2.3: 跨品牌客户去重、统一触达频控、交叉推荐策略
金额单位：分(fen)
"""

import json
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class GrowthCrossBrandService:
    """跨品牌增长服务 — 客户去重 + 统一触达历史 + 交叉推荐"""

    # 集团级总频控硬限制
    MAX_CROSS_BRAND_DAY = 5
    MAX_CROSS_BRAND_WEEK = 15

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    async def _set_tenant(self, db: AsyncSession, tenant_id: str) -> None:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

    # ------------------------------------------------------------------
    # 跨品牌统一画像
    # ------------------------------------------------------------------

    async def get_customer_cross_brand_profile(self, customer_id: UUID, tenant_id: str, db: AsyncSession) -> dict:
        """获取客户跨品牌统一画像"""
        await self._set_tenant(db, tenant_id)

        # 各品牌下的增长状态
        brand_profiles = await db.execute(
            text("""
            SELECT
                cgp.brand_id,
                gbc.brand_name,
                cgp.repurchase_stage,
                cgp.reactivation_priority,
                cgp.super_user_level,
                cgp.psych_distance_level,
                cgp.last_order_at,
                cgp.growth_milestone_stage
            FROM customer_growth_profiles cgp
            LEFT JOIN growth_brand_configs gbc
                ON gbc.brand_id = cgp.brand_id AND gbc.tenant_id = cgp.tenant_id
            WHERE cgp.customer_id = :cid AND cgp.is_deleted = FALSE
        """),
            {"cid": str(customer_id)},
        )

        brands = [dict(row._mapping) for row in brand_profiles.fetchall()]

        # 统一触达历史（跨品牌合并）
        touch_summary = await db.execute(
            text("""
            SELECT
                brand_id,
                COUNT(*) AS total_touches,
                COUNT(*) FILTER (WHERE execution_state IN ('opened','clicked','replied')) AS engaged,
                COUNT(*) FILTER (WHERE attributed_order_id IS NOT NULL) AS attributed,
                MAX(created_at) AS last_touch_at
            FROM growth_touch_executions
            WHERE customer_id = :cid AND is_deleted = FALSE
            GROUP BY brand_id
        """),
            {"cid": str(customer_id)},
        )

        touches_by_brand = [dict(row._mapping) for row in touch_summary.fetchall()]

        # 跨品牌总计
        total_touch = await db.execute(
            text("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE created_at::date = CURRENT_DATE) AS today,
                COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days') AS week
            FROM growth_touch_executions
            WHERE customer_id = :cid AND is_deleted = FALSE
              AND execution_state NOT IN ('blocked','skipped')
        """),
            {"cid": str(customer_id)},
        )
        tt = total_touch.fetchone()

        return {
            "customer_id": str(customer_id),
            "brand_profiles": brands,
            "brand_count": len(brands),
            "touch_by_brand": touches_by_brand,
            "cross_brand_touch_total": tt[0] if tt else 0,
            "cross_brand_touch_today": tt[1] if tt else 0,
            "cross_brand_touch_week": tt[2] if tt else 0,
        }

    # ------------------------------------------------------------------
    # 跨品牌频控检查
    # ------------------------------------------------------------------

    async def check_cross_brand_frequency(self, customer_id: UUID, tenant_id: str, db: AsyncSession) -> dict:
        """跨品牌频控检查 — 一个客户在所有品牌下的总触达不超限"""
        await self._set_tenant(db, tenant_id)

        result = await db.execute(
            text("""
            SELECT
                COUNT(*) FILTER (WHERE created_at::date = CURRENT_DATE) AS today,
                COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days') AS week
            FROM growth_touch_executions
            WHERE customer_id = :cid AND is_deleted = FALSE
              AND execution_state NOT IN ('blocked','skipped')
        """),
            {"cid": str(customer_id)},
        )
        r = result.fetchone()
        today = r[0] if r else 0
        week = r[1] if r else 0

        can_touch = today < self.MAX_CROSS_BRAND_DAY and week < self.MAX_CROSS_BRAND_WEEK

        block_reason: Optional[str] = None
        if today >= self.MAX_CROSS_BRAND_DAY:
            block_reason = "cross_brand_day_limit"
        elif week >= self.MAX_CROSS_BRAND_WEEK:
            block_reason = "cross_brand_week_limit"

        return {
            "customer_id": str(customer_id),
            "today_count": today,
            "week_count": week,
            "day_limit": self.MAX_CROSS_BRAND_DAY,
            "week_limit": self.MAX_CROSS_BRAND_WEEK,
            "can_touch": can_touch,
            "block_reason": block_reason,
        }

    # ------------------------------------------------------------------
    # 跨品牌增长机会发现
    # ------------------------------------------------------------------

    async def find_cross_brand_opportunities(
        self,
        tenant_id: str,
        db: AsyncSession,
        min_brands: int = 2,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """发现跨品牌增长机会 — 在A品牌活跃但B品牌沉默的客户"""
        await self._set_tenant(db, tenant_id)

        offset = (page - 1) * size

        # 查在多个品牌下有画像的客户
        result = await db.execute(
            text("""
            WITH multi_brand_customers AS (
                SELECT customer_id, COUNT(DISTINCT brand_id) AS brand_count
                FROM customer_growth_profiles
                WHERE is_deleted = FALSE AND brand_id IS NOT NULL
                GROUP BY customer_id
                HAVING COUNT(DISTINCT brand_id) >= :min_brands
            ),
            brand_detail AS (
                SELECT
                    mbc.customer_id,
                    mbc.brand_count,
                    cgp.brand_id,
                    gbc.brand_name,
                    cgp.repurchase_stage,
                    cgp.reactivation_priority,
                    cgp.super_user_level
                FROM multi_brand_customers mbc
                JOIN customer_growth_profiles cgp
                    ON cgp.customer_id = mbc.customer_id AND cgp.is_deleted = FALSE
                LEFT JOIN growth_brand_configs gbc
                    ON gbc.brand_id = cgp.brand_id AND gbc.tenant_id = cgp.tenant_id
            )
            SELECT
                customer_id, brand_count,
                json_agg(json_build_object(
                    'brand_id', brand_id,
                    'brand_name', brand_name,
                    'repurchase_stage', repurchase_stage,
                    'reactivation_priority', reactivation_priority,
                    'super_user_level', super_user_level
                ) ORDER BY brand_name) AS brands
            FROM brand_detail
            GROUP BY customer_id, brand_count
            ORDER BY brand_count DESC
            LIMIT :size OFFSET :offset
        """),
            {"min_brands": min_brands, "size": size, "offset": offset},
        )

        items = []
        for row in result.fetchall():
            brands_data = row[2] if isinstance(row[2], list) else json.loads(row[2]) if row[2] else []

            # 找机会：某品牌活跃(stable_repeat)但另一品牌沉默(high/critical)
            active_brands = [
                b for b in brands_data if b.get("repurchase_stage") in ("second_order_done", "stable_repeat")
            ]
            silent_brands = [b for b in brands_data if b.get("reactivation_priority") in ("high", "critical")]

            opportunity = None
            if active_brands and silent_brands:
                opportunity = {
                    "type": "cross_brand_reactivation",
                    "description": (
                        f"在{active_brands[0].get('brand_name', '?')}活跃"
                        f"但在{silent_brands[0].get('brand_name', '?')}沉默"
                    ),
                    "recommended_action": "用活跃品牌的关系唤醒沉默品牌",
                }

            items.append(
                {
                    "customer_id": str(row[0]),
                    "brand_count": row[1],
                    "brands": brands_data,
                    "opportunity": opportunity,
                }
            )

        # 总数
        count_result = await db.execute(
            text("""
            SELECT COUNT(*) FROM (
                SELECT customer_id
                FROM customer_growth_profiles
                WHERE is_deleted = FALSE AND brand_id IS NOT NULL
                GROUP BY customer_id
                HAVING COUNT(DISTINCT brand_id) >= :min_brands
            ) sub
        """),
            {"min_brands": min_brands},
        )
        total = count_result.scalar() or 0

        return {"items": items, "total": total, "page": page, "size": size}

    # ------------------------------------------------------------------
    # 跨品牌推荐策略
    # ------------------------------------------------------------------

    async def get_cross_brand_recommendation(
        self,
        customer_id: UUID,
        source_brand_id: UUID,
        target_brand_id: UUID,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """为特定客户生成跨品牌推荐策略"""
        await self._set_tenant(db, tenant_id)

        # 源品牌画像
        source = await db.execute(
            text("""
            SELECT repurchase_stage, super_user_level, growth_milestone_stage, psych_distance_level
            FROM customer_growth_profiles
            WHERE customer_id = :cid AND brand_id = :bid AND is_deleted = FALSE
        """),
            {"cid": str(customer_id), "bid": str(source_brand_id)},
        )
        src = source.fetchone()

        # 目标品牌画像
        target = await db.execute(
            text("""
            SELECT repurchase_stage, reactivation_priority, psych_distance_level
            FROM customer_growth_profiles
            WHERE customer_id = :cid AND brand_id = :bid AND is_deleted = FALSE
        """),
            {"cid": str(customer_id), "bid": str(target_brand_id)},
        )
        tgt = target.fetchone()

        if not src or not tgt:
            return {"ok": False, "error": "Profile not found for one or both brands"}

        # 推荐策略
        recommendation = {
            "customer_id": str(customer_id),
            "source_brand_id": str(source_brand_id),
            "target_brand_id": str(target_brand_id),
            "source_profile": {
                "repurchase_stage": src[0],
                "super_user_level": src[1],
                "milestone": src[2],
                "psych_distance": src[3],
            },
            "target_profile": {
                "repurchase_stage": tgt[0],
                "reactivation_priority": tgt[1],
                "psych_distance": tgt[2],
            },
        }

        # 推荐机制
        if src[1] in ("active", "advocate") and tgt[1] in ("high", "critical"):
            recommendation["strategy"] = "super_user_cross_referral"
            recommendation["mechanism"] = "social_proof"
            recommendation["description"] = "利用客户在源品牌的超级用户身份，通过社会证明引导到目标品牌"
            recommendation["suggested_journey"] = "channel_reflow_v1"
        elif src[0] == "stable_repeat" and tgt[2] in ("fading", "abstracted"):
            recommendation["strategy"] = "relationship_bridge"
            recommendation["mechanism"] = "relationship_warmup"
            recommendation["description"] = "客户与源品牌关系稳定，用关系唤醒策略重建与目标品牌的连接"
            recommendation["suggested_journey"] = "psych_distance_bridge_v1"
        else:
            recommendation["strategy"] = "standard_reactivation"
            recommendation["mechanism"] = "loss_aversion"
            recommendation["description"] = "标准召回策略，提醒客户在目标品牌的已有权益"
            recommendation["suggested_journey"] = "reactivation_loss_aversion_v2"

        return recommendation
