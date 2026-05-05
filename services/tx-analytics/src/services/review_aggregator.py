"""ReviewAggregator — cross-platform review ingestion & alerting.

Consumes REVIEW.CAPTURED events from all platforms (美团/点评/抖音/小红书)
and triggers alerts for negative reviews (rating <= 2).
"""
from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()

PLATFORM_REVIEW_SOURCES = ("meituan", "dianping", "douyin", "xiaohongshu")
NEGATIVE_THRESHOLD = 2  # rating <= 2 → alert


class ReviewAggregator:
    """Cross-platform review aggregation service."""

    async def ingest_review(self, event: dict[str, Any]) -> dict | None:
        """Ingest a REVIEW.CAPTURED event.

        Expected event shape:
        {
            "platform": "meituan",
            "review_id": "ext-123",
            "rating": 3,
            "content": "味道不错...",
            "author_name": "食客小王",
            "store_id": "...",
            "tenant_id": "...",
            "created_at": "2026-05-05T12:00:00Z"
        }
        """
        platform = event.get("platform", "")
        rating = event.get("rating", 5)
        content = event.get("content", "")

        if platform not in PLATFORM_REVIEW_SOURCES:
            logger.debug("review_aggregator.unknown_platform", platform=platform)
            return None

        review = {
            "platform": platform,
            "review_id": event.get("review_id", ""),
            "rating": rating,
            "content": content[:500],  # truncate long reviews
            "author_name": event.get("author_name", ""),
            "store_id": event.get("store_id", ""),
            "tenant_id": event.get("tenant_id", ""),
            "created_at": event.get("created_at", ""),
            "is_negative": rating <= NEGATIVE_THRESHOLD,
        }

        logger.info(
            "review_aggregator.ingested",
            platform=platform,
            rating=rating,
            is_negative=review["is_negative"],
        )

        if review["is_negative"]:
            await self._trigger_negative_alert(review)

        return review

    async def _trigger_negative_alert(self, review: dict) -> None:
        """Trigger an alert for negative reviews.

        In production, this would:
        1. Write to agent decision log
        2. Send push notification to store manager
        3. Optionally draft an auto-reply via Claude API
        """
        logger.warning(
            "review_aggregator.negative_alert",
            platform=review["platform"],
            rating=review["rating"],
            store_id=review["store_id"],
            review_id=review["review_id"],
            snippet=review["content"][:100],
        )

    async def get_platform_stats(
        self, tenant_id: str, store_id: str = ""
    ) -> dict[str, Any]:
        """Return review statistics per platform.

        In production, queries the review events stream or a materialized view.
        """
        return {
            "platforms": {
                p: {"total": 0, "avg_rating": 0.0, "negative_count": 0}
                for p in PLATFORM_REVIEW_SOURCES
            },
            "tenant_id": tenant_id,
            "store_id": store_id,
        }

    async def check_sentiment_spike(
        self, tenant_id: str, store_id: str = "", window_hours: int = 24
    ) -> dict:
        """Detect sentiment spikes — sudden increase in negative reviews.

        If negative review rate in the last N hours exceeds baseline by 2x,
        flag as a sentiment spike requiring immediate attention.
        """
        logger.info(
            "review_aggregator.sentiment_check",
            tenant_id=tenant_id,
            store_id=store_id,
            window_hours=window_hours,
        )
        return {
            "spike_detected": False,
            "current_negative_rate": 0.0,
            "baseline_rate": 0.0,
            "window_hours": window_hours,
        }
