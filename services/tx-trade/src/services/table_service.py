"""
TunxiangOS Smart Table Card - Data Aggregation Service
Module: services/tx-trade/src/services/table_service.py

High-level service for fetching tables with resolved smart card context.
Integrates context resolver and learning engine.
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, and_, func
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
            # TODO: Implement actual database queries
            # For now, return empty response structure
            tables = []
            stats = TableStatistics()

            return TableListResponse(
                summary=stats,
                meal_period="dinner",
                tables=tables,
                total_count=0,
            )

        except Exception as e:
            logger.error(f"Failed to fetch tables: {e}")
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
            # TODO: Implement actual database query
            # Query table, orders, customer, reservation in parallel

            table_data = {
                "table_id": table_id,
                "table_no": "A01",
                "area": "å¤§å",
                "seats": 4,
                "status": "dining",
                "layout": {"pos_x": 45, "pos_y": 30},
            }

            order_summary = {
                "items_count": 5,
                "items_pending": 2,
                "amount": 680.00,
                "duration_minutes": 45,
            }

            customer_info = {
                "customer_id": "cust_001",
                "name": "ææ»",
                "rfm_level": "S1",
                "visit_count": 25,
            }

            card = ResolvedTableCard(
                table_id=table_id,
                table_no=table_data["table_no"],
                area=table_data["area"],
                seats=table_data["seats"],
                status=table_data["status"],
                layout=table_data["layout"],
                card_fields=[],
                updated_at=datetime.utcnow(),
            )

            return TableDetailResponse(
                table=card,
                order_summary=order_summary,
                customer_info=customer_info,
            )

        except Exception as e:
            logger.error(f"Failed to fetch table detail: {e}")
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
            new_status: New status value (empty, dining, reserved, etc.)
            metadata: Optional metadata for status change

        Returns:
            True if update successful
        """
        try:
            # TODO: Implement actual status update
            # UPDATE tables SET status = ?, updated_at = ? WHERE id = ? AND store_id = ? AND tenant_id = ?

            logger.info(f"Updated table {table_id} status to {new_status}")
            return True

        except Exception as e:
            logger.error(f"Failed to update table status: {e}")
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
            # TODO: Implement actual statistics query
            # SELECT status, COUNT(*) FROM tables WHERE store_id = ? AND tenant_id = ? GROUP BY status

            stats = TableStatistics(
                empty_count=8,
                dining_count=12,
                reserved_count=3,
                pending_checkout_count=2,
                pending_cleanup_count=1,
            )
            stats.total_occupied = (
                stats.dining_count
                + stats.reserved_count
                + stats.pending_checkout_count
                + stats.pending_cleanup_count
            )
            stats.total_available = stats.empty_count

            return stats

        except Exception as e:
            logger.error(f"Failed to fetch table statistics: {e}")
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
            # TODO: Implement actual area statistics query
            # SELECT area, status, COUNT(*) FROM tables WHERE store_id = ? AND tenant_id = ? GROUP BY area, status

            return {
                "å¤§å": TableStatistics(
                    empty_count=5,
                    dining_count=8,
                    reserved_count=2,
                ),
                "åé´": TableStatistics(
                    empty_count=2,
                    dining_count=3,
                    reserved_count=1,
                ),
                "å§å°": TableStatistics(
                    empty_count=1,
                    dining_count=1,
                ),
            }

        except Exception as e:
            logger.error(f"Failed to fetch area statistics: {e}")
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
            # TODO: Implement actual search
            # SELECT * FROM tables WHERE store_id = ? AND tenant_id = ? AND (table_no ILIKE ? OR area ILIKE ?)

            return []

        except Exception as e:
            logger.error(f"Failed to search tables: {e}")
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
            logger.error(f"Failed to export table snapshot: {e}")
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
            urgent = [
                t
                for t in response.tables
                if any(f.get("alert") == "critical" for f in t.card_fields)
            ]

            return urgent

        except Exception as e:
            logger.error(f"Failed to get tables needing attention: {e}")
            raise
