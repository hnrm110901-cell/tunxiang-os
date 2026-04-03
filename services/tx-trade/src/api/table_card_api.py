"""
TunxiangOS Smart Table Card - API Router
Module: services/tx-trade/src/api/table_card_api.py

FastAPI router for smart table card endpoints.
Handles context resolution, learning, and statistics.
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, Query, HTTPException, Body
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ============================================================================
# Request/Response Models
# ============================================================================

class TableCardRequest(BaseModel):
    """Request to resolve table card fields."""
    model_config = ConfigDict(from_attributes=True)

    store_id: str = Field(description="Store ID")
    area: Optional[str] = Field(default=None, description="Filter by area")
    status: Optional[str] = Field(default=None, description="Filter by status")
    business_type: str = Field(default="standard", description="Business type")
    view_mode: str = Field(default="card", description="View mode: card, list, or map")
    meal_period: Optional[str] = Field(default=None, description="Meal period override")
    limit: int = Field(default=100, le=500, description="Limit results")
    offset: int = Field(default=0, ge=0, description="Offset for pagination")


class FieldClickRequest(BaseModel):
    """Request to record a field click."""
    field_key: str = Field(description="Field key that was clicked")
    table_no: str = Field(description="Table number")
    meal_period: str = Field(description="Current meal period")
    metadata: Optional[Dict[str, Any]] = Field(default=None)


class FieldRankingResponse(BaseModel):
    """Field ranking information."""
    field_key: str
    score: float = Field(ge=0, le=100)
    click_count: int
    last_clicked_at: Optional[datetime] = None


class TableCardFieldResponse(BaseModel):
    """Resolved field for table card."""
    key: str
    label: str
    value: Any
    priority: int = Field(ge=0, le=100)
    alert: str  # normal, warning, critical
    render_hint: Optional[str] = None


class TableCardResponse(BaseModel):
    """Resolved table card response."""
    table_id: str
    table_no: str
    area: str
    seats: int
    status: str
    guest_count: Optional[int] = None
    layout: Optional[Dict[str, Any]] = None
    card_fields: List[TableCardFieldResponse]
    updated_at: datetime


class TablesListResponse(BaseModel):
    """Response for list tables endpoint."""
    summary: Dict[str, int]
    meal_period: str
    tables: List[TableCardResponse]
    total_count: int


class StatisticsResponse(BaseModel):
    """Table statistics response."""
    empty_count: int
    dining_count: int
    reserved_count: int
    pending_checkout_count: int
    pending_cleanup_count: int
    total_occupied: int
    total_available: int
    timestamp: datetime


class LearningStatsResponse(BaseModel):
    """Learning statistics response."""
    store_id: str
    meal_period: Optional[str]
    total_clicks: int
    unique_fields: int
    field_clicks: Dict[str, int]
    days_active: int
    avg_clicks_per_field: float


# ============================================================================
# Router Setup
# ============================================================================

def create_table_card_router(
    context_resolver,
    table_service,
    learning_engine=None,
) -> APIRouter:
    """
    Create FastAPI router for table card endpoints.

    Args:
        context_resolver: TableCardContextResolver instance
        table_service: TableCardService instance
        learning_engine: Optional learning engine instance

    Returns:
        APIRouter with all table card endpoints
    """
    router = APIRouter(prefix="/api/v1/tables", tags=["table-card"])

    # ========== GET Endpoints ==========

    @router.get(
        "/",
        response_model=TablesListResponse,
        summary="Get tables with smart card context",
        description="Fetch list of tables with resolved smart card fields",
    )
    async def list_tables(
        store_id: str = Query(description="Store ID"),
        area: Optional[str] = Query(None, description="Filter by area"),
        status: Optional[str] = Query(None, description="Filter by status"),
        business_type: str = Query("standard", description="Business type"),
        view_mode: str = Query("card", description="View mode"),
        meal_period: Optional[str] = Query(None, description="Meal period"),
        limit: int = Query(100, le=500),
        offset: int = Query(0, ge=0),
        # Dependency injection (would use actual auth/tenant in production)
        db: AsyncSession = Depends(lambda: None),
        tenant_id: str = Query(description="Tenant ID"),
    ):
        """
        Get list of tables with context-aware smart card fields.

        Query Parameters:
        - store_id: Required store ID
        - area: Optional area filter
        - status: Optional status filter (empty, dining, reserved, etc.)
        - business_type: Business type (pro, standard, lite)
        - view_mode: Display mode (card, list, map)
        - meal_period: Meal period (breakfast, lunch, dinner, late_night)
        - limit: Max results (1-500)
        - offset: Pagination offset
        """
        try:
            # TODO: Implement actual table list logic
            # - Query tables from database
            # - Filter by area, status as requested
            # - Resolve fields using context_resolver
            # - Apply business_type preset rules
            # - Sort by priority
            # - Return paginated results

            return TablesListResponse(
                summary={
                    "empty": 8,
                    "dining": 12,
                    "reserved": 3,
                    "pending_checkout": 2,
                    "pending_cleanup": 1,
                },
                meal_period=meal_period or "dinner",
                tables=[],
                total_count=0,
            )

        except Exception as e:
            logger.error(f"Failed to list tables: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get(
        "/{table_id}",
        response_model=TableCardResponse,
        summary="Get single table detail",
        description="Fetch detailed information for a specific table",
    )
    async def get_table_detail(
        table_id: str,
        store_id: str = Query(description="Store ID"),
        db: AsyncSession = Depends(lambda: None),
        tenant_id: str = Query(description="Tenant ID"),
    ):
        """
        Get detailed information for a specific table.

        Returns full card fields plus related order and customer data.
        """
        try:
            # TODO: Implement actual table detail logic
            # - Query table by ID
            # - Load related orders, customers, reservations
            # - Resolve all card fields
            # - Return detailed response

            return TableCardResponse(
                table_id=table_id,
                table_no="A01",
                area="å¤§å",
                seats=4,
                status="dining",
                card_fields=[],
                updated_at=datetime.utcnow(),
            )

        except Exception as e:
            logger.error(f"Failed to get table detail: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get(
        "/statistics",
        response_model=StatisticsResponse,
        summary="Get table statistics",
        description="Get aggregate statistics for tables in a store",
    )
    async def get_statistics(
        store_id: str = Query(description="Store ID"),
        db: AsyncSession = Depends(lambda: None),
        tenant_id: str = Query(description="Tenant ID"),
    ):
        """
        Get aggregate table statistics by status.

        Returns counts of tables in each status (empty, dining, reserved, etc.)
        """
        try:
            # TODO: Implement actual statistics query
            # - Count tables by status
            # - Calculate occupancy rate
            # - Return aggregate stats

            return StatisticsResponse(
                empty_count=8,
                dining_count=12,
                reserved_count=3,
                pending_checkout_count=2,
                pending_cleanup_count=1,
                total_occupied=18,
                total_available=8,
                timestamp=datetime.utcnow(),
            )

        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get(
        "/field-rankings",
        response_model=List[FieldRankingResponse],
        summary="Get learned field rankings",
        description="Get field importance rankings based on staff click patterns",
    )
    async def get_field_rankings(
        store_id: str = Query(description="Store ID"),
        meal_period: Optional[str] = Query(None, description="Meal period filter"),
        limit: int = Query(10, le=50),
        db: AsyncSession = Depends(lambda: None),
        tenant_id: str = Query(description="Tenant ID"),
    ):
        """
        Get learned field importance rankings.

        Returns fields sorted by how often staff have clicked them,
        with exponential decay applied to older clicks.
        """
        try:
            if not learning_engine:
                return []

            # TODO: Implement field ranking logic
            # - Get click history from learning_engine
            # - Apply decay algorithm
            # - Sort by score
            # - Return top N fields

            rankings = await learning_engine.get_field_rankings(
                store_id=store_id,
                meal_period=meal_period,
                tenant_id=tenant_id,
                limit=limit,
            )

            return [
                FieldRankingResponse(
                    field_key=k,
                    score=v,
                    click_count=0,  # TODO: Get actual count
                )
                for k, v in rankings.items()
            ]

        except Exception as e:
            logger.error(f"Failed to get field rankings: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # ========== POST Endpoints ==========

    @router.post(
        "/click-log",
        status_code=201,
        summary="Record field click",
        description="Record when user clicks on a field for learning",
    )
    async def record_click(
        request: FieldClickRequest = Body(description="Click event details"),
        store_id: str = Query(description="Store ID"),
        db: AsyncSession = Depends(lambda: None),
        tenant_id: str = Query(description="Tenant ID"),
        user_id: Optional[str] = Query(None, description="User ID who clicked"),
    ):
        """
        Record a field click event for learning.

        Click events are tracked per field, store, and meal period,
        then aggregated to learn field importance patterns.
        """
        try:
            if not learning_engine:
                return {"recorded": False}

            # TODO: Implement click recording logic
            success = await learning_engine.record_click(
                field_key=request.field_key,
                store_id=store_id,
                table_no=request.table_no,
                meal_period=request.meal_period,
                tenant_id=tenant_id,
                user_id=user_id,
                metadata=request.metadata,
            )

            return {
                "recorded": success,
                "field_key": request.field_key,
                "timestamp": datetime.utcnow(),
            }

        except Exception as e:
            logger.error(f"Failed to record click: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # ========== PUT Endpoints ==========

    @router.put(
        "/{table_id}/status",
        summary="Update table status",
        description="Update table status (empty, dining, reserved, etc.)",
    )
    async def update_table_status(
        table_id: str,
        new_status: str = Body(description="New status value"),
        store_id: str = Query(description="Store ID"),
        db: AsyncSession = Depends(lambda: None),
        tenant_id: str = Query(description="Tenant ID"),
    ):
        """
        Update table status (state transition).

        Valid status values: empty, dining, reserved, pending_checkout, pending_cleanup
        """
        try:
            # TODO: Implement status update logic
            # - Validate new_status value
            # - Update table in database
            # - Trigger any state-specific actions
            # - Return updated table

            return {
                "table_id": table_id,
                "new_status": new_status,
                "updated_at": datetime.utcnow(),
            }

        except Exception as e:
            logger.error(f"Failed to update table status: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # ========== Learning Endpoints ==========

    @router.get(
        "/learning/stats",
        response_model=LearningStatsResponse,
        summary="Get learning statistics",
        description="Get learning statistics for a store",
    )
    async def get_learning_stats(
        store_id: str = Query(description="Store ID"),
        meal_period: Optional[str] = Query(None, description="Meal period filter"),
        db: AsyncSession = Depends(lambda: None),
        tenant_id: str = Query(description="Tenant ID"),
    ):
        """
        Get learning statistics showing field click patterns.

        Useful for understanding which fields staff prioritize.
        """
        try:
            if not learning_engine:
                return LearningStatsResponse(
                    store_id=store_id,
                    meal_period=meal_period,
                    total_clicks=0,
                    unique_fields=0,
                    field_clicks={},
                    days_active=0,
                    avg_clicks_per_field=0.0,
                )

            stats = await learning_engine.get_learning_stats(
                store_id=store_id,
                tenant_id=tenant_id,
                meal_period=meal_period,
            )

            return LearningStatsResponse(**stats)

        except Exception as e:
            logger.error(f"Failed to get learning stats: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post(
        "/learning/reset",
        summary="Reset learning data",
        description="Reset learning data for a store (for testing/reset)",
    )
    async def reset_learning(
        store_id: str = Query(description="Store ID"),
        meal_period: Optional[str] = Query(None, description="Meal period to reset (None=all)"),
        db: AsyncSession = Depends(lambda: None),
        tenant_id: str = Query(description="Tenant ID"),
    ):
        """
        Reset learning data for a store.

        Clears all click history and learned rankings.
        Use with caution - typically only for testing or migration.
        """
        try:
            if not learning_engine:
                return {"reset_count": 0}

            count = await learning_engine.reset_learning(
                store_id=store_id,
                tenant_id=tenant_id,
                meal_period=meal_period,
            )

            return {
                "reset_count": count,
                "store_id": store_id,
                "meal_period": meal_period,
                "timestamp": datetime.utcnow(),
            }

        except Exception as e:
            logger.error(f"Failed to reset learning: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return router


# ============================================================================
# Health Check Endpoint
# ============================================================================

def create_health_router() -> APIRouter:
    """Create a simple health check router."""
    router = APIRouter(prefix="/health", tags=["health"])

    @router.get("/")
    async def health_check():
        """Health check endpoint."""
        return {"status": "ok", "timestamp": datetime.utcnow()}

    return router
