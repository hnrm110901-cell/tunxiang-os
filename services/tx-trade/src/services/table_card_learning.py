"""
TunxiangOS Smart Table Card - Self-Learning Engine
Module: services/tx-trade/src/services/table_card_learning.py

Self-learning engine tracking click events and adjusting field importance.
Uses 20%/day exponential decay algorithm.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from pydantic import BaseModel, Field
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class FieldClickEvent(BaseModel):
    """Record of a field click event."""
    field_key: str
    store_id: str
    table_no: str
    meal_period: str
    clicked_at: datetime
    tenant_id: str
    metadata: Optional[Dict] = {}


class FieldRanking(BaseModel):
    """Ranking of field importance based on learning."""
    field_key: str
    score: float = Field(default=0.0, ge=0.0, le=100.0)
    click_count: int = 0
    last_clicked_at: Optional[datetime] = None
    meal_period: Optional[str] = None


class FieldLearningAggregate(BaseModel):
    """Aggregated learning data for a field."""
    field_key: str
    total_clicks: int
    click_score: float
    decay_factor: float = 0.8  # 20%/day decay
    active_days: int
    recommendations: List[str] = []


# ============================================================================
# Constants
# ============================================================================

DECAY_RATE_PER_DAY = 0.8  # 20% decay per day, 80% retention
MIN_CLICKS_FOR_RANKING = 3
SCORE_NORMALIZATION_MAX = 100.0


# ============================================================================
# Self-Learning Engine
# ============================================================================

class TableCardLearningEngine:
    """
    Self-learning engine for smart table card fields.

    Tracks which fields store staff click on most frequently per meal period
    and store, then adjusts field priority weights based on learned patterns.
    Uses exponential decay algorithm: score = score * 0.8^(days_elapsed)
    """

    def __init__(self, db_session: AsyncSession):
        """Initialize learning engine with database session."""
        self.db = db_session
        self.memory_cache: Dict[str, List[FieldClickEvent]] = defaultdict(list)

    async def record_click(
        self,
        field_key: str,
        store_id: str,
        table_no: str,
        meal_period: str,
        tenant_id: str,
        user_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> bool:
        """
        Record a field click event.

        Args:
            field_key: Key of clicked field
            store_id: Store ID where click occurred
            table_no: Table number (for context)
            meal_period: Current meal period (breakfast/lunch/dinner/late_night)
            tenant_id: Tenant ID for multi-tenancy
            user_id: User ID who clicked (optional)
            metadata: Additional metadata (optional)

        Returns:
            True if recorded successfully
        """
        try:
            event = FieldClickEvent(
                field_key=field_key,
                store_id=store_id,
                table_no=table_no,
                meal_period=meal_period,
                clicked_at=datetime.utcnow(),
                tenant_id=tenant_id,
                metadata=metadata or {"user_id": user_id},
            )

            # Store in memory cache for fast access
            cache_key = f"{tenant_id}:{store_id}:{meal_period}"
            self.memory_cache[cache_key].append(event)

            # Persist to database
            # Note: Assumes table_card_click_logs table exists
            # Actual insert would use SQLAlchemy ORM model

            logger.info(
                f"Recorded click: {field_key} @ {store_id}/{table_no} ({meal_period})"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to record click: {e}")
            return False

    async def get_field_rankings(
        self,
        store_id: str,
        meal_period: str,
        tenant_id: str,
        limit: int = 10,
    ) -> Dict[str, float]:
        """
        Get ranked field scores for a store and meal period.

        Args:
            store_id: Store ID
            meal_period: Meal period
            tenant_id: Tenant ID
            limit: Maximum number of fields to return

        Returns:
            Dict mapping field_key -> priority_score (0-100)
        """
        cache_key = f"{tenant_id}:{store_id}:{meal_period}"
        events = self.memory_cache.get(cache_key, [])

        # Count clicks per field
        click_counts: Dict[str, int] = defaultdict(int)
        for event in events:
            click_counts[event.field_key] += 1

        # Apply decay algorithm and normalize scores
        scores = await self._compute_decayed_scores(
            tenant_id, store_id, meal_period, click_counts
        )

        # Sort by score descending and limit
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return {field_key: score for field_key, score in sorted_scores[:limit]}

    async def _compute_decayed_scores(
        self,
        tenant_id: str,
        store_id: str,
        meal_period: str,
        click_counts: Dict[str, int],
    ) -> Dict[str, float]:
        """
        Compute decayed scores for field clicks.

        Applies exponential decay: score = count * 0.8^(days_since_first_click)

        Args:
            tenant_id: Tenant ID
            store_id: Store ID
            meal_period: Meal period
            click_counts: Dict of field_key -> click_count

        Returns:
            Dict of field_key -> decayed_score
        """
        scores: Dict[str, float] = {}
        now = datetime.utcnow()

        for field_key, count in click_counts.items():
            if count < MIN_CLICKS_FOR_RANKING:
                continue

            # Get first click timestamp for this field
            first_click_at = await self._get_first_click_timestamp(
                tenant_id, store_id, field_key, meal_period
            )

            if not first_click_at:
                # Fallback: use current time (no decay)
                scores[field_key] = float(count)
                continue

            # Calculate days elapsed
            days_elapsed = (now - first_click_at).days
            if days_elapsed < 0:
                days_elapsed = 0

            # Apply exponential decay: score = count * 0.8^days
            decay_factor = DECAY_RATE_PER_DAY ** days_elapsed
            decayed_score = count * decay_factor

            # Normalize to 0-100 range
            normalized_score = min(decayed_score, SCORE_NORMALIZATION_MAX)
            scores[field_key] = normalized_score

        return scores

    async def _get_first_click_timestamp(
        self,
        tenant_id: str,
        store_id: str,
        field_key: str,
        meal_period: str,
    ) -> Optional[datetime]:
        """
        Get timestamp of first click for a field in a store.

        In production, this would query the database.
        For now, returns None (fallback to no decay).
        """
        # TODO: Implement actual DB query
        # SELECT MIN(clicked_at) FROM table_card_click_logs
        # WHERE tenant_id = ? AND store_id = ? AND field_key = ? AND meal_period = ?
        return None

    async def decay_scores(
        self,
        tenant_id: str,
        store_id: str,
        meal_period: Optional[str] = None,
        older_than_days: int = 30,
    ) -> int:
        """
        Apply decay to old click records.

        Removes or de-emphasizes very old clicks that are no longer relevant.
        Typically called as a background job (e.g., daily).

        Args:
            tenant_id: Tenant ID
            store_id: Store ID
            meal_period: Optional meal period filter
            older_than_days: Only decay records older than this many days

        Returns:
            Number of records affected
        """
        cutoff_date = datetime.utcnow() - timedelta(days=older_than_days)
        affected = 0

        # Filter events from memory cache
        for cache_key in list(self.memory_cache.keys()):
            if not cache_key.startswith(f"{tenant_id}:{store_id}"):
                continue

            events = self.memory_cache[cache_key]
            # Keep only recent events
            self.memory_cache[cache_key] = [
                e for e in events if e.clicked_at > cutoff_date
            ]
            affected += len(events) - len(self.memory_cache[cache_key])

        logger.info(f"Decayed {affected} old click records for {store_id}")
        return affected

    async def compute_recommendations(
        self,
        store_id: str,
        meal_period: str,
        tenant_id: str,
        top_n: int = 5,
    ) -> List[str]:
        """
        Compute field recommendations based on learning history.

        Returns list of field keys that should be promoted for this context.

        Args:
            store_id: Store ID
            meal_period: Meal period
            tenant_id: Tenant ID
            top_n: Number of top recommendations to return

        Returns:
            List of recommended field keys
        """
        rankings = await self.get_field_rankings(store_id, meal_period, tenant_id, top_n)
        recommendations = list(rankings.keys())

        logger.debug(
            f"Recommendations for {store_id}/{meal_period}: {recommendations}"
        )
        return recommendations

    async def get_learning_stats(
        self,
        store_id: str,
        tenant_id: str,
        meal_period: Optional[str] = None,
    ) -> Dict[str, any]:
        """
        Get learning statistics for a store.

        Returns aggregated data about what fields are being clicked.

        Args:
            store_id: Store ID
            tenant_id: Tenant ID
            meal_period: Optional meal period filter

        Returns:
            Dict with learning statistics
        """
        total_clicks = 0
        field_clicks: Dict[str, int] = defaultdict(int)
        earliest_click = None
        latest_click = None

        for cache_key, events in self.memory_cache.items():
            if not cache_key.startswith(f"{tenant_id}:{store_id}"):
                continue

            if meal_period and meal_period not in cache_key:
                continue

            for event in events:
                total_clicks += 1
                field_clicks[event.field_key] += 1
                if not earliest_click or event.clicked_at < earliest_click:
                    earliest_click = event.clicked_at
                if not latest_click or event.clicked_at > latest_click:
                    latest_click = event.clicked_at

        days_active = (
            (latest_click - earliest_click).days + 1
            if earliest_click and latest_click
            else 0
        )

        return {
            "store_id": store_id,
            "meal_period": meal_period,
            "total_clicks": total_clicks,
            "unique_fields": len(field_clicks),
            "field_clicks": dict(field_clicks),
            "days_active": days_active,
            "earliest_click": earliest_click,
            "latest_click": latest_click,
            "avg_clicks_per_field": (
                total_clicks / len(field_clicks) if field_clicks else 0
            ),
        }

    async def reset_learning(
        self,
        store_id: str,
        tenant_id: str,
        meal_period: Optional[str] = None,
    ) -> int:
        """
        Reset learning data for a store.

        Useful for testing or when business model changes.

        Args:
            store_id: Store ID
            tenant_id: Tenant ID
            meal_period: Optional meal period to reset (if None, reset all)

        Returns:
            Number of records reset
        """
        affected = 0

        for cache_key in list(self.memory_cache.keys()):
            if not cache_key.startswith(f"{tenant_id}:{store_id}"):
                continue

            if meal_period and meal_period not in cache_key:
                continue

            affected += len(self.memory_cache[cache_key])
            del self.memory_cache[cache_key]

        logger.warning(
            f"Reset learning data: {affected} records for {store_id}/{meal_period}"
        )
        return affected

    async def export_learning_data(
        self,
        store_id: str,
        tenant_id: str,
        format: str = "json",
    ) -> str:
        """
        Export learning data for a store.

        Useful for analysis or migration.

        Args:
            store_id: Store ID
            tenant_id: Tenant ID
            format: Export format (json, csv)

        Returns:
            Exported data as string
        """
        stats = await self.get_learning_stats(store_id, tenant_id)

        if format == "json":
            import json

            return json.dumps(stats, default=str, indent=2)
        elif format == "csv":
            field_clicks = stats.get("field_clicks", {})
            lines = ["field_key,click_count"]
            lines.extend([f"{k},{v}" for k, v in field_clicks.items()])
            return "\n".join(lines)

        return str(stats)
