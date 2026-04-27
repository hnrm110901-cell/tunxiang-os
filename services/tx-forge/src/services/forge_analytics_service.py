"""Forge 分析服务 — 市场统计、热门应用、分类分析

职责：
  1. get_marketplace_stats() — 市场全局统计
  2. get_trending_apps()     — 热门应用排行
  3. get_category_stats()    — 分类维度统计
"""

from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import APP_CATEGORIES

logger = structlog.get_logger(__name__)


class ForgeAnalyticsService:
    """应用市场分析"""

    async def get_marketplace_stats(self, db: AsyncSession) -> dict:
        """市场全局汇总指标。"""
        result = await db.execute(
            text("""
                SELECT
                    COUNT(*)                                          AS total_apps,
                    COUNT(*) FILTER (WHERE status = 'published')      AS published_apps,
                    COUNT(DISTINCT developer_id)                       AS total_developers,
                    COALESCE(SUM(install_count), 0)                   AS total_installs,
                    COALESCE(SUM(revenue_total_fen), 0)               AS total_revenue_fen,
                    COALESCE(
                        AVG(rating) FILTER (WHERE status = 'published'
                                             AND rating > 0), 0
                    )                                                 AS avg_rating
                FROM forge_apps
            """)
        )
        agg = dict(result.mappings().one())

        # 分类分布
        cat_result = await db.execute(
            text("""
                SELECT category, COUNT(*) AS app_count
                FROM forge_apps
                GROUP BY category
                ORDER BY app_count DESC
            """)
        )
        category_distribution = [
            {
                "category": r["category"],
                "category_name": APP_CATEGORIES.get(r["category"], {}).get("name", r["category"]),
                "app_count": r["app_count"],
            }
            for r in cat_result.mappings().all()
        ]

        agg["avg_rating"] = round(float(agg["avg_rating"]), 2)
        agg["category_distribution"] = category_distribution

        logger.info("marketplace_stats_queried", **{k: v for k, v in agg.items() if k != "category_distribution"})
        return agg

    async def get_trending_apps(
        self,
        db: AsyncSession,
        *,
        period: str = "week",
        limit: int = 10,
    ) -> list[dict]:
        """热门应用排行：install_count * 0.6 + rating * 40（归一化）。"""
        result = await db.execute(
            text("""
                SELECT
                    a.app_id,
                    a.app_name,
                    d.name              AS developer_name,
                    a.category,
                    a.rating,
                    a.install_count,
                    a.price_display,
                    (a.install_count * 0.6 + COALESCE(a.rating, 0) * 40)
                        AS trend_score
                FROM forge_apps a
                JOIN forge_developers d ON d.developer_id = a.developer_id
                WHERE a.status = 'published'
                ORDER BY trend_score DESC
                LIMIT :limit
            """),
            {"limit": limit},
        )
        rows = result.mappings().all()
        return [
            {
                "rank": idx + 1,
                **dict(r),
                "trend_score": round(float(r["trend_score"]), 2),
            }
            for idx, r in enumerate(rows)
        ]

    async def get_category_stats(self, db: AsyncSession) -> list[dict]:
        """按分类聚合应用统计。"""
        result = await db.execute(
            text("""
                SELECT
                    category,
                    COUNT(*)                              AS app_count,
                    COALESCE(SUM(install_count), 0)       AS total_installs,
                    COALESCE(SUM(revenue_total_fen), 0)   AS total_revenue_fen,
                    COALESCE(AVG(rating) FILTER (WHERE rating > 0), 0)
                                                          AS avg_rating
                FROM forge_apps
                GROUP BY category
                ORDER BY total_installs DESC
            """)
        )
        return [
            {
                **dict(r),
                "category_name": APP_CATEGORIES.get(r["category"], {}).get("name", r["category"]),
                "avg_rating": round(float(r["avg_rating"]), 2),
            }
            for r in result.mappings().all()
        ]
