"""品牌级增长配置服务 — 管理 growth_brand_configs 表 + 品牌级预算/频控检查

V2.2 Sprint F: 多品牌架构
金额单位：分(fen)
"""
import json
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class GrowthBrandService:
    """品牌级增长配置 CRUD + 预算/频控校验"""

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    async def _set_tenant(self, db: AsyncSession, tenant_id: str) -> None:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

    # ------------------------------------------------------------------
    # 品牌配置 CRUD
    # ------------------------------------------------------------------

    async def get_brand_config(
        self, brand_id: UUID, tenant_id: str, db: AsyncSession
    ) -> Optional[dict]:
        """获取品牌增长配置，不存在返回 None"""
        await self._set_tenant(db, tenant_id)

        result = await db.execute(
            text("""
                SELECT id, tenant_id, brand_id, brand_name,
                       growth_enabled, daily_touch_budget,
                       monthly_offer_budget_fen,
                       max_touch_per_customer_day,
                       max_touch_per_customer_week,
                       enabled_channels, enabled_journey_types,
                       auto_approve_low_risk, auto_approve_medium_risk,
                       margin_floor_pct,
                       is_deleted, created_at, updated_at
                FROM growth_brand_configs
                WHERE brand_id = :brand_id
                  AND is_deleted = FALSE
                LIMIT 1
            """),
            {"brand_id": str(brand_id)},
        )
        row = result.fetchone()
        if row is None:
            return None
        return {
            "id": str(row[0]),
            "tenant_id": str(row[1]),
            "brand_id": str(row[2]),
            "brand_name": row[3],
            "growth_enabled": row[4],
            "daily_touch_budget": row[5],
            "monthly_offer_budget_fen": row[6],
            "max_touch_per_customer_day": row[7],
            "max_touch_per_customer_week": row[8],
            "enabled_channels": row[9],
            "enabled_journey_types": row[10],
            "auto_approve_low_risk": row[11],
            "auto_approve_medium_risk": row[12],
            "margin_floor_pct": row[13],
            "is_deleted": row[14],
            "created_at": row[15].isoformat() if row[15] else None,
            "updated_at": row[16].isoformat() if row[16] else None,
        }

    async def upsert_brand_config(
        self, brand_id: UUID, data: dict, tenant_id: str, db: AsyncSession
    ) -> dict:
        """创建或更新品牌配置（INSERT ... ON CONFLICT UPDATE）"""
        await self._set_tenant(db, tenant_id)

        config_id = str(uuid4())
        brand_name = data.get("brand_name", "")
        growth_enabled = data.get("growth_enabled", True)
        daily_touch_budget = data.get("daily_touch_budget", 100)
        monthly_offer_budget_fen = data.get("monthly_offer_budget_fen", 1000000)
        max_touch_day = data.get("max_touch_per_customer_day", 2)
        max_touch_week = data.get("max_touch_per_customer_week", 5)
        enabled_channels = json.dumps(
            data.get("enabled_channels", ["wecom", "miniapp", "sms"])
        )
        enabled_journey_types = json.dumps(
            data.get(
                "enabled_journey_types",
                ["first_to_second", "reactivation", "service_repair",
                 "stored_value", "banquet", "channel_reflow"],
            )
        )
        auto_approve_low = data.get("auto_approve_low_risk", False)
        auto_approve_medium = data.get("auto_approve_medium_risk", False)
        margin_floor_pct = data.get("margin_floor_pct", 30)

        result = await db.execute(
            text("""
                INSERT INTO growth_brand_configs
                    (id, tenant_id, brand_id, brand_name,
                     growth_enabled, daily_touch_budget,
                     monthly_offer_budget_fen,
                     max_touch_per_customer_day,
                     max_touch_per_customer_week,
                     enabled_channels, enabled_journey_types,
                     auto_approve_low_risk, auto_approve_medium_risk,
                     margin_floor_pct)
                VALUES
                    (:id, :tenant_id, :brand_id, :brand_name,
                     :growth_enabled, :daily_touch_budget,
                     :monthly_offer_budget_fen,
                     :max_touch_day, :max_touch_week,
                     :enabled_channels::jsonb, :enabled_journey_types::jsonb,
                     :auto_approve_low, :auto_approve_medium,
                     :margin_floor_pct)
                ON CONFLICT (tenant_id, brand_id) DO UPDATE SET
                    brand_name = EXCLUDED.brand_name,
                    growth_enabled = EXCLUDED.growth_enabled,
                    daily_touch_budget = EXCLUDED.daily_touch_budget,
                    monthly_offer_budget_fen = EXCLUDED.monthly_offer_budget_fen,
                    max_touch_per_customer_day = EXCLUDED.max_touch_per_customer_day,
                    max_touch_per_customer_week = EXCLUDED.max_touch_per_customer_week,
                    enabled_channels = EXCLUDED.enabled_channels,
                    enabled_journey_types = EXCLUDED.enabled_journey_types,
                    auto_approve_low_risk = EXCLUDED.auto_approve_low_risk,
                    auto_approve_medium_risk = EXCLUDED.auto_approve_medium_risk,
                    margin_floor_pct = EXCLUDED.margin_floor_pct,
                    updated_at = NOW()
                RETURNING id, created_at, updated_at
            """),
            {
                "id": config_id,
                "tenant_id": tenant_id,
                "brand_id": str(brand_id),
                "brand_name": brand_name,
                "growth_enabled": growth_enabled,
                "daily_touch_budget": daily_touch_budget,
                "monthly_offer_budget_fen": monthly_offer_budget_fen,
                "max_touch_day": max_touch_day,
                "max_touch_week": max_touch_week,
                "enabled_channels": enabled_channels,
                "enabled_journey_types": enabled_journey_types,
                "auto_approve_low": auto_approve_low,
                "auto_approve_medium": auto_approve_medium,
                "margin_floor_pct": margin_floor_pct,
            },
        )
        row = result.fetchone()
        await db.commit()

        logger.info(
            "brand_config_upserted",
            brand_id=str(brand_id),
            tenant_id=tenant_id,
        )
        return {
            "id": str(row[0]),
            "brand_id": str(brand_id),
            "created_at": row[1].isoformat() if row[1] else None,
            "updated_at": row[2].isoformat() if row[2] else None,
        }

    async def list_brand_configs(
        self, tenant_id: str, db: AsyncSession
    ) -> dict:
        """列出该租户所有品牌配置"""
        await self._set_tenant(db, tenant_id)

        result = await db.execute(
            text("""
                SELECT id, brand_id, brand_name, growth_enabled,
                       daily_touch_budget, monthly_offer_budget_fen,
                       max_touch_per_customer_day, max_touch_per_customer_week,
                       enabled_channels, enabled_journey_types,
                       auto_approve_low_risk, auto_approve_medium_risk,
                       margin_floor_pct, created_at, updated_at
                FROM growth_brand_configs
                WHERE is_deleted = FALSE
                ORDER BY created_at DESC
            """)
        )
        rows = result.fetchall()
        items = []
        for row in rows:
            items.append({
                "id": str(row[0]),
                "brand_id": str(row[1]),
                "brand_name": row[2],
                "growth_enabled": row[3],
                "daily_touch_budget": row[4],
                "monthly_offer_budget_fen": row[5],
                "max_touch_per_customer_day": row[6],
                "max_touch_per_customer_week": row[7],
                "enabled_channels": row[8],
                "enabled_journey_types": row[9],
                "auto_approve_low_risk": row[10],
                "auto_approve_medium_risk": row[11],
                "margin_floor_pct": row[12],
                "created_at": row[13].isoformat() if row[13] else None,
                "updated_at": row[14].isoformat() if row[14] else None,
            })
        return {"items": items, "total": len(items)}

    # ------------------------------------------------------------------
    # 预算检查
    # ------------------------------------------------------------------

    async def check_brand_budget(
        self, brand_id: UUID, tenant_id: str, db: AsyncSession
    ) -> dict:
        """检查品牌今日触达量 / 本月offer金额 vs 配置上限

        返回:
            daily_touch_used / daily_touch_limit
            monthly_offer_used_fen / monthly_offer_limit_fen
            budget_ok: bool
        """
        await self._set_tenant(db, tenant_id)

        # 获取配置
        cfg = await db.execute(
            text("""
                SELECT daily_touch_budget, monthly_offer_budget_fen
                FROM growth_brand_configs
                WHERE brand_id = :brand_id AND is_deleted = FALSE
                LIMIT 1
            """),
            {"brand_id": str(brand_id)},
        )
        cfg_row = cfg.fetchone()
        if cfg_row is None:
            return {
                "daily_touch_used": 0,
                "daily_touch_limit": None,
                "monthly_offer_used_fen": 0,
                "monthly_offer_limit_fen": None,
                "budget_ok": True,
                "config_exists": False,
            }

        daily_limit = cfg_row[0]
        monthly_limit_fen = cfg_row[1]

        # 今日触达数
        touch_result = await db.execute(
            text("""
                SELECT COUNT(*)
                FROM growth_touch_executions
                WHERE brand_id = :brand_id
                  AND is_deleted = FALSE
                  AND created_at >= CURRENT_DATE
            """),
            {"brand_id": str(brand_id)},
        )
        daily_used = touch_result.scalar() or 0

        # 本月offer金额（attributed_revenue_fen 中有归因的触达总额）
        offer_result = await db.execute(
            text("""
                SELECT COALESCE(SUM(
                    CASE WHEN attributed_order_id IS NOT NULL
                         THEN COALESCE(attributed_revenue_fen, 0)
                         ELSE 0
                    END
                ), 0)
                FROM growth_touch_executions
                WHERE brand_id = :brand_id
                  AND is_deleted = FALSE
                  AND created_at >= date_trunc('month', CURRENT_DATE)
            """),
            {"brand_id": str(brand_id)},
        )
        monthly_used_fen = offer_result.scalar() or 0

        budget_ok = (daily_used < daily_limit) and (monthly_used_fen < monthly_limit_fen)

        return {
            "daily_touch_used": daily_used,
            "daily_touch_limit": daily_limit,
            "monthly_offer_used_fen": monthly_used_fen,
            "monthly_offer_limit_fen": monthly_limit_fen,
            "budget_ok": budget_ok,
            "config_exists": True,
        }

    # ------------------------------------------------------------------
    # 频控检查
    # ------------------------------------------------------------------

    async def check_brand_frequency(
        self,
        brand_id: UUID,
        customer_id: UUID,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """检查品牌级客户频控

        返回:
            today_count / day_limit
            week_count / week_limit
            can_touch: bool
        """
        await self._set_tenant(db, tenant_id)

        # 获取配置
        cfg = await db.execute(
            text("""
                SELECT max_touch_per_customer_day, max_touch_per_customer_week
                FROM growth_brand_configs
                WHERE brand_id = :brand_id AND is_deleted = FALSE
                LIMIT 1
            """),
            {"brand_id": str(brand_id)},
        )
        cfg_row = cfg.fetchone()
        if cfg_row is None:
            return {
                "today_count": 0,
                "day_limit": None,
                "week_count": 0,
                "week_limit": None,
                "can_touch": True,
                "config_exists": False,
            }

        day_limit = cfg_row[0]
        week_limit = cfg_row[1]

        # 今日触达数
        today_result = await db.execute(
            text("""
                SELECT COUNT(*)
                FROM growth_touch_executions
                WHERE brand_id = :brand_id
                  AND customer_id = :customer_id
                  AND is_deleted = FALSE
                  AND created_at >= CURRENT_DATE
            """),
            {"brand_id": str(brand_id), "customer_id": str(customer_id)},
        )
        today_count = today_result.scalar() or 0

        # 本周触达数（周一起算）
        week_result = await db.execute(
            text("""
                SELECT COUNT(*)
                FROM growth_touch_executions
                WHERE brand_id = :brand_id
                  AND customer_id = :customer_id
                  AND is_deleted = FALSE
                  AND created_at >= date_trunc('week', CURRENT_DATE)
            """),
            {"brand_id": str(brand_id), "customer_id": str(customer_id)},
        )
        week_count = week_result.scalar() or 0

        can_touch = (today_count < day_limit) and (week_count < week_limit)

        return {
            "today_count": today_count,
            "day_limit": day_limit,
            "week_count": week_count,
            "week_limit": week_limit,
            "can_touch": can_touch,
            "config_exists": True,
        }
