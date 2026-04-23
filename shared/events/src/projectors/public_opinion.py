"""PublicOpinionProjector — 舆情监控投影器

消费事件：
  opinion.mention_captured  → 新舆情记录，更新mv_public_opinion统计
  opinion.resolved          → 已处理，更新is_resolved

维护视图：mv_public_opinion（按ISO周聚合）
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from ..projector import ProjectorBase


def _iso_week_monday(dt: datetime) -> "datetime.date":
    """返回该日期所在ISO周的周一。"""
    d = dt.date()
    return d - timedelta(days=d.weekday())


class PublicOpinionProjector(ProjectorBase):
    name = "public_opinion"
    event_types = {
        "opinion.mention_captured",
        "opinion.resolved",
    }

    async def handle(self, event: dict[str, Any], conn: object) -> None:
        store_id = event.get("store_id")
        if not store_id:
            return

        occurred_at = event["occurred_at"]
        if isinstance(occurred_at, str):
            occurred_at = datetime.fromisoformat(occurred_at)

        payload = event.get("payload") or {}
        event_type = event["event_type"]

        if event_type == "opinion.mention_captured":
            await self._handle_mention_captured(event, conn, occurred_at, store_id, payload)

        elif event_type == "opinion.resolved":
            await self._handle_resolved(event, conn, store_id, payload)

    async def _handle_mention_captured(
        self,
        event: dict[str, Any],
        conn: object,
        occurred_at: datetime,
        store_id: str,
        payload: dict[str, Any],
    ) -> None:
        """处理新舆情记录事件，UPSERT mv_public_opinion 统计行。"""
        stat_week = _iso_week_monday(occurred_at)
        platform = payload.get("platform", "unknown")
        sentiment = payload.get("sentiment", "neutral")
        rating = payload.get("rating")
        sentiment_score = payload.get("sentiment_score")

        # 按 (tenant_id, store_id, stat_week, platform) UPSERT 统计行
        await conn.execute(  # type: ignore[union-attr]
            """
            INSERT INTO mv_public_opinion
                (tenant_id, store_id, stat_week, platform, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (tenant_id, store_id, stat_week, platform) DO NOTHING
            """,
            self.tenant_id,
            UUID(str(store_id)),
            stat_week,
            platform,
        )

        # 情感计数增量
        sentiment_col = {
            "positive": "positive_count",
            "negative": "negative_count",
        }.get(sentiment, "neutral_count")

        await conn.execute(  # type: ignore[union-attr]
            f"""
            UPDATE mv_public_opinion
            SET total_mentions  = total_mentions + 1,
                {sentiment_col} = {sentiment_col} + 1,
                updated_at      = NOW()
            WHERE tenant_id = $1 AND store_id = $2
              AND stat_week = $3 AND platform = $4
            """,
            self.tenant_id,
            UUID(str(store_id)),
            stat_week,
            platform,
        )

        # 重算平均评分（仅当本次带有 rating/sentiment_score 时更新）
        if rating is not None or sentiment_score is not None:
            await _recalc_averages(
                conn,
                self.tenant_id,
                UUID(str(store_id)),
                stat_week,
                platform,
                new_rating=float(rating) if rating is not None else None,
                new_sentiment_score=float(sentiment_score) if sentiment_score is not None else None,
            )

    async def _handle_resolved(
        self,
        event: dict[str, Any],
        conn: object,
        store_id: str,
        payload: dict[str, Any],
    ) -> None:
        """处理舆情已处理事件，更新 public_opinion_mentions.is_resolved。"""
        mention_id = payload.get("mention_id")
        resolution_note = payload.get("resolution_note", "")

        if not mention_id:
            return

        await conn.execute(  # type: ignore[union-attr]
            """
            UPDATE public_opinion_mentions
            SET is_resolved     = true,
                resolution_note = $2
            WHERE id = $1
              AND tenant_id = $3
            """,
            UUID(str(mention_id)),
            resolution_note,
            self.tenant_id,
        )


async def _recalc_averages(
    conn: object,
    tenant_id: UUID,
    store_id: UUID,
    stat_week: object,
    platform: str,
    new_rating: "float | None",
    new_sentiment_score: "float | None",
) -> None:
    """增量滚动更新平均评分（加权平均近似：将新值纳入当前均值）。

    采用增量公式：
      new_avg = (old_avg * (total - 1) + new_val) / total
    这样避免全量扫描 mentions 表。
    """
    if new_rating is not None:
        await conn.execute(  # type: ignore[union-attr]
            """
            UPDATE mv_public_opinion
            SET avg_rating = CASE
                WHEN total_mentions > 0
                THEN ROUND(
                    (COALESCE(avg_rating, $5) * (total_mentions - 1) + $5)
                    / total_mentions,
                    2
                )
                ELSE $5
            END,
            updated_at = NOW()
            WHERE tenant_id = $1 AND store_id = $2
              AND stat_week = $3 AND platform = $4
            """,
            tenant_id,
            store_id,
            stat_week,
            platform,
            new_rating,
        )

    if new_sentiment_score is not None:
        await conn.execute(  # type: ignore[union-attr]
            """
            UPDATE mv_public_opinion
            SET avg_sentiment_score = CASE
                WHEN total_mentions > 0
                THEN ROUND(
                    (COALESCE(avg_sentiment_score, $5) * (total_mentions - 1) + $5)
                    / total_mentions,
                    2
                )
                ELSE $5
            END,
            updated_at = NOW()
            WHERE tenant_id = $1 AND store_id = $2
              AND stat_week = $3 AND platform = $4
            """,
            tenant_id,
            store_id,
            stat_week,
            platform,
            new_sentiment_score,
        )
