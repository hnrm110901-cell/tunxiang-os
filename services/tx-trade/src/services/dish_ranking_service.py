"""实时三榜单服务 — 畅销/滞销/退菜

KDS 数据驱动的实时菜品排行榜，每次调用直接查询当日数据。
不依赖 Redis，所有聚合均在 PostgreSQL 完成。

三榜单说明：
  hot_dishes   — 今日出单量 TOP10（按出品任务数降序）
  cold_dishes  — 今日最低出单量 10 条（含零出单），配合库存状态
  remake_dishes — 今日退菜/重做量 TOP10（按重做次数降序），附退菜率
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import List, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

TOP_N = 10                  # 榜单条目上限
REMAKE_RATE_DAYS = 7        # 退菜率统计近N天窗口


@dataclass
class DishRankItem:
    """榜单单条目"""
    dish_id: str
    dish_name: str
    count: int              # 出单数/退菜数
    rate: float             # 退菜率（0.0~1.0），非退菜榜为 0.0
    rank: int               # 排名（1 开始）


@dataclass
class DishRankings:
    """三榜单结果集"""
    hot: List[DishRankItem] = field(default_factory=list)
    cold: List[DishRankItem] = field(default_factory=list)
    remake: List[DishRankItem] = field(default_factory=list)
    as_of: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class DishRankingService:
    """实时三榜单服务

    数据源：order_items 表（出单/退菜统计）
    查询时间范围：今日（按 created_at 日期过滤）
    租户隔离：所有查询均带 tenant_id + store_id
    """

    @staticmethod
    async def get_rankings(
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
        query_date: Optional[date] = None,
    ) -> DishRankings:
        """获取三榜单

        Args:
            store_id: 门店ID
            tenant_id: 租户ID
            db: 数据库会话
            query_date: 查询日期（默认今天）

        Returns:
            DishRankings 包含 hot/cold/remake 三个列表
        """
        if query_date is None:
            query_date = date.today()

        date_str = query_date.isoformat()

        try:
            hot = await DishRankingService._query_hot(store_id, tenant_id, db, date_str)
            remake = await DishRankingService._query_remake(store_id, tenant_id, db, date_str)
            cold = await DishRankingService._query_cold(store_id, tenant_id, db, date_str)
        except SQLAlchemyError as exc:  # MLPS3-P0: 异常收窄
            logger.error(
                "dish_ranking.get_rankings_failed",
                store_id=store_id,
                date=date_str,
                error=str(exc),
            )
            raise RuntimeError(f"Failed to get dish rankings: {exc}") from exc

        rankings = DishRankings(
            hot=hot,
            cold=cold,
            remake=remake,
            as_of=datetime.now(timezone.utc),
        )
        logger.info(
            "dish_ranking.get_rankings",
            store_id=store_id,
            date=date_str,
            hot_count=len(hot),
            cold_count=len(cold),
            remake_count=len(remake),
        )
        return rankings

    # ── 私有查询方法 ──────────────────────────────────────────

    @staticmethod
    async def _query_hot(
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
        date_str: str,
    ) -> List[DishRankItem]:
        """畅销榜：今日出单量 TOP10（按出品任务数降序）"""
        result = await db.execute(
            text(
                """
                SELECT
                    oi.dish_id::text,
                    oi.item_name           AS dish_name,
                    COUNT(oi.id)           AS order_count
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id
                WHERE oi.tenant_id = :tenant_id
                  AND o.store_id   = :store_id
                  AND oi.return_flag = false
                  AND oi.is_deleted = false
                  AND o.is_deleted  = false
                  AND DATE(oi.created_at AT TIME ZONE 'Asia/Shanghai') = :date_str
                GROUP BY oi.dish_id, oi.item_name
                ORDER BY order_count DESC
                LIMIT :top_n
                """
            ),
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "date_str": date_str,
                "top_n": TOP_N,
            },
        )
        rows = result.fetchall()
        return [
            DishRankItem(
                dish_id=str(row.dish_id) if row.dish_id else "",
                dish_name=row.dish_name,
                count=row.order_count,
                rate=0.0,
                rank=idx + 1,
            )
            for idx, row in enumerate(rows)
        ]

    @staticmethod
    async def _query_remake(
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
        date_str: str,
    ) -> List[DishRankItem]:
        """退菜榜：今日退菜/重做 TOP10（按退菜次数降序），含退菜率

        退菜率 = 今日退菜数 / 今日总出单数（同菜品）
        """
        result = await db.execute(
            text(
                """
                WITH today_items AS (
                    SELECT
                        oi.dish_id,
                        oi.item_name,
                        COUNT(oi.id)                                          AS total_count,
                        COUNT(oi.id) FILTER (WHERE oi.return_flag = true)     AS remake_count
                    FROM order_items oi
                    JOIN orders o ON o.id = oi.order_id
                    WHERE oi.tenant_id = :tenant_id
                      AND o.store_id   = :store_id
                      AND oi.is_deleted = false
                      AND o.is_deleted  = false
                      AND DATE(oi.created_at AT TIME ZONE 'Asia/Shanghai') = :date_str
                    GROUP BY oi.dish_id, oi.item_name
                )
                SELECT
                    dish_id::text,
                    item_name   AS dish_name,
                    remake_count,
                    total_count,
                    CASE WHEN total_count > 0
                         THEN ROUND(remake_count::numeric / total_count, 4)
                         ELSE 0.0
                    END AS remake_rate
                FROM today_items
                WHERE remake_count > 0
                ORDER BY remake_count DESC, remake_rate DESC
                LIMIT :top_n
                """
            ),
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "date_str": date_str,
                "top_n": TOP_N,
            },
        )
        rows = result.fetchall()
        return [
            DishRankItem(
                dish_id=str(row.dish_id) if row.dish_id else "",
                dish_name=row.dish_name,
                count=row.remake_count,
                rate=float(row.remake_rate),
                rank=idx + 1,
            )
            for idx, row in enumerate(rows)
        ]

    @staticmethod
    async def _query_cold(
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
        date_str: str,
    ) -> List[DishRankItem]:
        """滞销榜：今日最低出单量10条（含零销量菜品）

        零销量菜品来自 dishes 主表（当日有效菜品），今日无出单则 count=0。
        """
        result = await db.execute(
            text(
                """
                WITH today_sold AS (
                    SELECT
                        oi.dish_id,
                        oi.item_name,
                        COUNT(oi.id) AS order_count
                    FROM order_items oi
                    JOIN orders o ON o.id = oi.order_id
                    WHERE oi.tenant_id = :tenant_id
                      AND o.store_id   = :store_id
                      AND oi.return_flag = false
                      AND oi.is_deleted  = false
                      AND o.is_deleted   = false
                      AND DATE(oi.created_at AT TIME ZONE 'Asia/Shanghai') = :date_str
                    GROUP BY oi.dish_id, oi.item_name
                ),
                active_dishes AS (
                    SELECT
                        d.id           AS dish_id,
                        d.dish_name    AS item_name
                    FROM dishes d
                    WHERE d.tenant_id = :tenant_id
                      AND d.is_deleted = false
                )
                SELECT
                    ad.dish_id::text,
                    ad.item_name    AS dish_name,
                    COALESCE(ts.order_count, 0) AS order_count
                FROM active_dishes ad
                LEFT JOIN today_sold ts ON ts.dish_id = ad.dish_id
                ORDER BY order_count ASC, ad.item_name ASC
                LIMIT :top_n
                """
            ),
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "date_str": date_str,
                "top_n": TOP_N,
            },
        )
        rows = result.fetchall()
        return [
            DishRankItem(
                dish_id=str(row.dish_id) if row.dish_id else "",
                dish_name=row.dish_name,
                count=row.order_count,
                rate=0.0,
                rank=idx + 1,
            )
            for idx, row in enumerate(rows)
        ]

    # ── 退菜率单独查询（供外部调用）──────────────────────────

    @staticmethod
    async def get_remake_rate(
        dish_id: str,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
        days: int = REMAKE_RATE_DAYS,
    ) -> float:
        """近N天退菜率 = 退菜次数 / 出单次数

        Args:
            dish_id: 菜品ID
            store_id: 门店ID
            tenant_id: 租户ID
            db: 数据库会话
            days: 统计天数窗口（默认7天）

        Returns:
            退菜率 0.0~1.0，若无出单记录返回 0.0
        """
        if days < 1:
            raise ValueError(f"days must be >= 1, got {days}")
        try:
            result = await db.execute(
                text(
                    """
                    SELECT
                        COUNT(oi.id)                                          AS total_count,
                        COUNT(oi.id) FILTER (WHERE oi.return_flag = true)     AS remake_count
                    FROM order_items oi
                    JOIN orders o ON o.id = oi.order_id
                    WHERE oi.tenant_id  = :tenant_id
                      AND o.store_id    = :store_id
                      AND oi.dish_id    = :dish_id
                      AND oi.is_deleted = false
                      AND o.is_deleted  = false
                      AND oi.created_at >= NOW() - CAST(:days || ' days' AS INTERVAL)
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "store_id": store_id,
                    "dish_id": dish_id,
                    "days": days,
                },
            )
            row = result.fetchone()
            if row is None or row.total_count == 0:
                return 0.0
            return round(row.remake_count / row.total_count, 4)
        except SQLAlchemyError as exc:  # MLPS3-P0: 异常收窄
            logger.error(
                "dish_ranking.get_remake_rate_failed",
                dish_id=dish_id,
                store_id=store_id,
                days=days,
                error=str(exc),
            )
            raise RuntimeError(f"Failed to get remake rate: {exc}") from exc
