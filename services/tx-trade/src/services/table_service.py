"""
TunxiangOS Smart Table Card - Data Aggregation Service
Module: services/tx-trade/src/services/table_service.py

High-level service for fetching tables with resolved smart card context.
Integrates context resolver and learning engine.
"""

import logging
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ViewMode(str, Enum):
    """Table display view modes."""

    CARD = "card"
    LIST = "list"
    MAP = "map"


class TableFilters(BaseModel):
    """Filters for table queries."""

    model_config = ConfigDict(from_attributes=True)

    store_id: str
    area: Optional[str] = None
    status: Optional[str] = None
    business_type: Optional[str] = None
    view_mode: ViewMode = ViewMode.CARD
    meal_period: Optional[str] = None
    is_active: bool = True
    limit: int = Field(default=100, le=500)
    offset: int = Field(default=0, ge=0)


class TableStatistics(BaseModel):
    """Statistics about table statuses."""

    empty_count: int = 0
    dining_count: int = 0
    reserved_count: int = 0
    pending_checkout_count: int = 0
    pending_cleanup_count: int = 0
    total_occupied: int = 0
    total_available: int = 0
    turnover_rate: Optional[float] = None


class ResolvedTableCard(BaseModel):
    """Resolved table card with context-aware fields."""

    model_config = ConfigDict(from_attributes=True)

    table_id: str
    table_no: str
    area: str
    seats: int
    status: str
    guest_count: Optional[int] = None
    layout: Optional[Dict[str, Any]] = None
    card_fields: List[Dict[str, Any]] = []
    updated_at: datetime
    metadata: Optional[Dict[str, Any]] = None


class TableDetailResponse(BaseModel):
    """Detailed response for single table."""

    table: ResolvedTableCard
    order_summary: Optional[Dict[str, Any]] = None
    customer_info: Optional[Dict[str, Any]] = None
    reservation_info: Optional[Dict[str, Any]] = None


class TableListResponse(BaseModel):
    """Response for table list queries."""

    summary: TableStatistics
    meal_period: str
    tables: List[ResolvedTableCard]
    total_count: int


# ============================================================================
# Table Service
# ============================================================================


class TableCardService:
    """
    High-level service for fetching and aggregating table data with smart card context.

    Coordinates between:
    - Database queries for tables, orders, customers, reservations
    - Context resolver for field prioritization
    - Learning engine for adaptive field ranking
    """

    def __init__(
        self,
        db_session: AsyncSession,
        context_resolver,
        learning_engine=None,
    ):
        """
        Initialize table service.

        Args:
            db_session: SQLAlchemy async session
            context_resolver: TableCardContextResolver instance
            learning_engine: Optional learning engine instance
        """
        self.db = db_session
        self.context_resolver = context_resolver
        self.learning_engine = learning_engine

    async def get_tables_with_context(
        self,
        filters: TableFilters,
    ) -> TableListResponse:
        """
        Get list of tables with resolved smart card context.

        Args:
            filters: TableFilters with query parameters

        Returns:
            TableListResponse with tables and statistics
        """
        try:
            # Build WHERE conditions
            conditions = [
                "t.store_id = :store_id",
                "t.is_deleted = FALSE",
            ]
            params: Dict[str, Any] = {"store_id": filters.store_id}

            if filters.is_active:
                conditions.append("t.is_active = TRUE")

            if filters.area:
                conditions.append("t.area = :area")
                params["area"] = filters.area

            if filters.status:
                conditions.append("t.status = :status")
                params["status"] = filters.status

            where_clause = " AND ".join(conditions)

            # Fetch tables with optional active dining session guest_count
            result = await self.db.execute(
                text(f"""
                    SELECT
                        t.id, t.table_no, t.area, t.seats, t.status,
                        t.config, t.updated_at,
                        ds.guest_count
                    FROM tables t
                    LEFT JOIN LATERAL (
                        SELECT guest_count
                        FROM dining_sessions ds2
                        WHERE ds2.table_id   = t.id
                          AND ds2.is_deleted = FALSE
                          AND ds2.status NOT IN ('paid', 'clearing', 'disabled')
                        ORDER BY ds2.opened_at DESC
                        LIMIT 1
                    ) ds ON TRUE
                    WHERE {where_clause}
                    ORDER BY t.area, t.table_no
                    LIMIT :limit OFFSET :offset
                """),
                {**params, "limit": filters.limit, "offset": filters.offset},
            )
            rows = result.mappings().all()

            # Total count without pagination
            count_result = await self.db.execute(
                text(f"SELECT COUNT(*) FROM tables t WHERE {where_clause}"),
                params,
            )
            total_count = count_result.scalar_one()

            # Aggregate stats for the store (all active, non-deleted tables)
            stats = await self.get_table_statistics(
                store_id=filters.store_id,
                tenant_id="",  # store_id-scoped query; tenant_id not needed here
            )

            tables = []
            for row in rows:
                config = row["config"] or {}
                layout = config.get("layout") if isinstance(config, dict) else None
                card = ResolvedTableCard(
                    table_id=str(row["id"]),
                    table_no=row["table_no"],
                    area=row["area"] or "",
                    seats=row["seats"],
                    status=row["status"],
                    guest_count=row["guest_count"],
                    layout=layout,
                    card_fields=[],
                    updated_at=row["updated_at"],
                )
                tables.append(card)

            # Derive meal period from current UTC hour (simple heuristic)
            hour = datetime.utcnow().hour
            if hour < 11:
                meal_period = "breakfast"
            elif hour < 14:
                meal_period = "lunch"
            elif hour < 17:
                meal_period = "teatime"
            else:
                meal_period = "dinner"

            return TableListResponse(
                summary=stats,
                meal_period=meal_period,
                tables=tables,
                total_count=total_count,
            )

        except SQLAlchemyError as e:
            logger.error(f"DB error fetching tables: {e}", exc_info=True)
            return TableListResponse(
                summary=TableStatistics(),
                meal_period="dinner",
                tables=[],
                total_count=0,
            )
        except Exception as e:
            logger.error(f"Failed to fetch tables: {e}", exc_info=True)
            raise

    async def get_table_detail(
        self,
        table_id: str,
        store_id: str,
        tenant_id: str,
    ) -> TableDetailResponse:
        """
        Get detailed information for a single table.

        Args:
            table_id: Table ID
            store_id: Store ID
            tenant_id: Tenant ID

        Returns:
            TableDetailResponse with full context
        """
        try:
            # Fetch table row
            table_result = await self.db.execute(
                text("""
                    SELECT id, table_no, area, seats, status, config, updated_at
                    FROM tables
                    WHERE id        = :table_id
                      AND store_id  = :store_id
                      AND tenant_id = :tenant_id
                      AND is_deleted = FALSE
                """),
                {"table_id": table_id, "store_id": store_id, "tenant_id": tenant_id},
            )
            row = table_result.mappings().one_or_none()
            if row is None:
                raise ValueError(f"Table {table_id} not found")

            config = row["config"] or {}
            layout = config.get("layout") if isinstance(config, dict) else None

            card = ResolvedTableCard(
                table_id=str(row["id"]),
                table_no=row["table_no"],
                area=row["area"] or "",
                seats=row["seats"],
                status=row["status"],
                layout=layout,
                card_fields=[],
                updated_at=row["updated_at"],
            )

            # Fetch current active dining session + aggregate order summary
            session_result = await self.db.execute(
                text("""
                    SELECT
                        ds.id              AS session_id,
                        ds.guest_count,
                        ds.total_amount_fen,
                        EXTRACT(EPOCH FROM (NOW() - ds.opened_at)) / 60 AS dining_minutes,
                        (
                            SELECT COUNT(*)
                            FROM orders o
                            WHERE o.table_id  = ds.table_id
                              AND o.tenant_id = ds.tenant_id
                              AND o.status NOT IN ('cancelled')
                        ) AS items_count
                    FROM dining_sessions ds
                    WHERE ds.table_id   = :table_id
                      AND ds.tenant_id  = :tenant_id
                      AND ds.is_deleted = FALSE
                      AND ds.status NOT IN ('paid', 'clearing', 'disabled')
                    ORDER BY ds.opened_at DESC
                    LIMIT 1
                """),
                {"table_id": table_id, "tenant_id": tenant_id},
            )
            session_row = session_result.mappings().one_or_none()

            order_summary: Optional[Dict[str, Any]] = None
            if session_row:
                card.guest_count = session_row["guest_count"]
                order_summary = {
                    "session_id": str(session_row["session_id"]),
                    "items_count": int(session_row["items_count"] or 0),
                    "amount_fen": int(session_row["total_amount_fen"] or 0),
                    "duration_minutes": int(session_row["dining_minutes"] or 0),
                }

            return TableDetailResponse(
                table=card,
                order_summary=order_summary,
                customer_info=None,
                reservation_info=None,
            )

        except SQLAlchemyError as e:
            logger.error(f"DB error fetching table detail {table_id}: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Failed to fetch table detail: {e}", exc_info=True)
            raise

    async def update_table_status(
        self,
        table_id: str,
        store_id: str,
        tenant_id: str,
        new_status: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Update table status (transition state).

        Args:
            table_id: Table ID
            store_id: Store ID
            tenant_id: Tenant ID
            new_status: New status value (free, occupied, reserved, cleaning, etc.)
            metadata: Optional metadata for status change

        Returns:
            True if update successful
        """
        try:
            result = await self.db.execute(
                text("""
                    UPDATE tables
                    SET status     = :new_status,
                        updated_at = NOW()
                    WHERE id        = :table_id
                      AND store_id  = :store_id
                      AND tenant_id = :tenant_id
                      AND is_deleted = FALSE
                """),
                {
                    "new_status": new_status,
                    "table_id": table_id,
                    "store_id": store_id,
                    "tenant_id": tenant_id,
                },
            )
            await self.db.commit()
            updated = result.rowcount > 0
            if updated:
                logger.info(
                    f"Updated table {table_id} status to {new_status}",
                    extra={"table_id": table_id, "new_status": new_status},
                )
            else:
                logger.warning(f"update_table_status: table {table_id} not found or not modified")
            return updated

        except SQLAlchemyError as e:
            logger.error(f"DB error updating table {table_id} status: {e}", exc_info=True)
            await self.db.rollback()
            return False
        except Exception as e:
            logger.error(f"Failed to update table status: {e}", exc_info=True)
            return False

    async def get_table_statistics(
        self,
        store_id: str,
        tenant_id: str,
    ) -> TableStatistics:
        """
        Get aggregate statistics for all tables in a store.

        Args:
            store_id: Store ID
            tenant_id: Tenant ID

        Returns:
            TableStatistics with counts by status
        """
        try:
            result = await self.db.execute(
                text("""
                    SELECT status, COUNT(*) AS cnt
                    FROM tables
                    WHERE store_id  = :store_id
                      AND is_active  = TRUE
                      AND is_deleted = FALSE
                    GROUP BY status
                """),
                {"store_id": store_id},
            )
            rows = result.mappings().all()

            # Map DB status values to TableStatistics fields
            # DB statuses: free, occupied, reserved, cleaning
            # TableStatistics fields: empty_count, dining_count, reserved_count,
            #                         pending_checkout_count, pending_cleanup_count
            counts: Dict[str, int] = {row["status"]: int(row["cnt"]) for row in rows}

            stats = TableStatistics(
                empty_count=counts.get("free", 0) + counts.get("empty", 0),
                dining_count=counts.get("occupied", 0) + counts.get("dining", 0),
                reserved_count=counts.get("reserved", 0),
                pending_checkout_count=counts.get("pending_checkout", 0),
                pending_cleanup_count=counts.get("cleaning", 0) + counts.get("pending_cleanup", 0),
            )
            stats.total_occupied = (
                stats.dining_count + stats.reserved_count + stats.pending_checkout_count + stats.pending_cleanup_count
            )
            stats.total_available = stats.empty_count

            return stats

        except SQLAlchemyError as e:
            logger.error(f"DB error fetching table statistics: {e}", exc_info=True)
            return TableStatistics()
        except Exception as e:
            logger.error(f"Failed to fetch table statistics: {e}", exc_info=True)
            raise

    async def batch_update_table_status(
        self,
        store_id: str,
        tenant_id: str,
        updates: List[Dict[str, Any]],
    ) -> Dict[str, bool]:
        """
        Batch update multiple table statuses.

        Args:
            store_id: Store ID
            tenant_id: Tenant ID
            updates: List of {table_id, new_status} dicts

        Returns:
            Dict mapping table_id -> success boolean
        """
        results = {}

        for update in updates:
            table_id = update.get("table_id")
            new_status = update.get("new_status")

            if not table_id or not new_status:
                results[table_id] = False
                continue

            success = await self.update_table_status(
                table_id=table_id,
                store_id=store_id,
                tenant_id=tenant_id,
                new_status=new_status,
            )
            results[table_id] = success

        return results

    async def get_area_statistics(
        self,
        store_id: str,
        tenant_id: str,
    ) -> Dict[str, TableStatistics]:
        """
        Get statistics grouped by area/zone.

        Args:
            store_id: Store ID
            tenant_id: Tenant ID

        Returns:
            Dict mapping area name -> TableStatistics
        """
        try:
            result = await self.db.execute(
                text("""
                    SELECT area, status, COUNT(*) AS cnt
                    FROM tables
                    WHERE store_id  = :store_id
                      AND is_active  = TRUE
                      AND is_deleted = FALSE
                    GROUP BY area, status
                    ORDER BY area, status
                """),
                {"store_id": store_id},
            )
            rows = result.mappings().all()

            # Aggregate per-area counts into TableStatistics objects
            area_counts: Dict[str, Dict[str, int]] = {}
            for row in rows:
                area = row["area"] or ""
                status = row["status"]
                cnt = int(row["cnt"])
                if area not in area_counts:
                    area_counts[area] = {}
                area_counts[area][status] = cnt

            area_stats: Dict[str, TableStatistics] = {}
            for area, counts in area_counts.items():
                s = TableStatistics(
                    empty_count=counts.get("free", 0) + counts.get("empty", 0),
                    dining_count=counts.get("occupied", 0) + counts.get("dining", 0),
                    reserved_count=counts.get("reserved", 0),
                    pending_checkout_count=counts.get("pending_checkout", 0),
                    pending_cleanup_count=counts.get("cleaning", 0) + counts.get("pending_cleanup", 0),
                )
                s.total_occupied = (
                    s.dining_count + s.reserved_count + s.pending_checkout_count + s.pending_cleanup_count
                )
                s.total_available = s.empty_count
                area_stats[area] = s

            return area_stats

        except SQLAlchemyError as e:
            logger.error(f"DB error fetching area statistics: {e}", exc_info=True)
            return {}
        except Exception as e:
            logger.error(f"Failed to fetch area statistics: {e}", exc_info=True)
            raise

    async def search_tables(
        self,
        store_id: str,
        tenant_id: str,
        query: str,
    ) -> List[ResolvedTableCard]:
        """
        Search tables by table number or area.

        Args:
            store_id: Store ID
            tenant_id: Tenant ID
            query: Search query (table number, area, customer name, etc.)

        Returns:
            List of matching ResolvedTableCard
        """
        try:
            search_pattern = f"%{query}%"
            result = await self.db.execute(
                text("""
                    SELECT id, table_no, area, seats, status, config, updated_at
                    FROM tables
                    WHERE store_id  = :store_id
                      AND tenant_id = :tenant_id
                      AND is_deleted = FALSE
                      AND is_active  = TRUE
                      AND (
                          table_no ILIKE :pattern
                          OR area  ILIKE :pattern
                      )
                    ORDER BY area, table_no
                    LIMIT 50
                """),
                {
                    "store_id": store_id,
                    "tenant_id": tenant_id,
                    "pattern": search_pattern,
                },
            )
            rows = result.mappings().all()

            cards = []
            for row in rows:
                config = row["config"] or {}
                layout = config.get("layout") if isinstance(config, dict) else None
                cards.append(
                    ResolvedTableCard(
                        table_id=str(row["id"]),
                        table_no=row["table_no"],
                        area=row["area"] or "",
                        seats=row["seats"],
                        status=row["status"],
                        layout=layout,
                        card_fields=[],
                        updated_at=row["updated_at"],
                    )
                )
            return cards

        except SQLAlchemyError as e:
            logger.error(f"DB error searching tables: {e}", exc_info=True)
            return []
        except Exception as e:
            logger.error(f"Failed to search tables: {e}", exc_info=True)
            raise

    async def export_table_snapshot(
        self,
        store_id: str,
        tenant_id: str,
        format: str = "json",
    ) -> str:
        """
        Export current table states for backup or analysis.

        Args:
            store_id: Store ID
            tenant_id: Tenant ID
            format: Export format (json, csv)

        Returns:
            Exported data as string
        """
        try:
            filters = TableFilters(store_id=store_id, limit=1000)
            response = await self.get_tables_with_context(filters)

            if format == "json":
                import json

                data = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "store_id": store_id,
                    "statistics": response.summary.model_dump(),
                    "tables": [t.model_dump() for t in response.tables],
                }
                return json.dumps(data, default=str, indent=2)

            elif format == "csv":
                lines = ["table_no,area,status,seats,guest_count,updated_at"]
                for table in response.tables:
                    lines.append(
                        f"{table.table_no},{table.area},{table.status},{table.seats},"
                        f"{table.guest_count},{table.updated_at}"
                    )
                return "\n".join(lines)

            return str(response)

        except Exception as e:
            logger.error(f"Failed to export table snapshot: {e}", exc_info=True)
            raise

    async def get_tables_by_status(
        self,
        store_id: str,
        tenant_id: str,
        status: str,
    ) -> List[ResolvedTableCard]:
        """
        Get all tables with a specific status.

        Args:
            store_id: Store ID
            tenant_id: Tenant ID
            status: Status filter

        Returns:
            List of tables with specified status
        """
        filters = TableFilters(store_id=store_id, status=status, limit=500)
        response = await self.get_tables_with_context(filters)
        return response.tables

    async def get_tables_needing_attention(
        self,
        store_id: str,
        tenant_id: str,
    ) -> List[ResolvedTableCard]:
        """
        Get tables that need immediate attention (long wait times, pending actions, etc.).

        Args:
            store_id: Store ID
            tenant_id: Tenant ID

        Returns:
            List of tables needing attention, sorted by urgency
        """
        try:
            filters = TableFilters(store_id=store_id, limit=500)
            response = await self.get_tables_with_context(filters)

            # Filter to tables with critical alerts
            urgent = [t for t in response.tables if any(f.get("alert") == "critical" for f in t.card_fields)]

            return urgent

        except Exception as e:
            logger.error(f"Failed to get tables needing attention: {e}", exc_info=True)
            raise
