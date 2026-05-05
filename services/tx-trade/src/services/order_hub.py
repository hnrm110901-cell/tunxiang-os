"""OrderHub — cross-platform unified order query engine."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .omni_channel_service import (
    OmniChannelService,
    row_omni_platform_key,
    row_omni_platform_order_id,
)

logger = structlog.get_logger()


@dataclass
class OrderHubFilters:
    platform: str = ""
    status: str = ""
    store_id: str = ""
    keyword: str = ""
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    page: int = 1
    size: int = 20


class OrderHub:
    PLATFORMS = OmniChannelService.PLATFORMS

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id

    async def list_orders(self, filters: OrderHubFilters) -> dict:
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self.tenant_id},
        )
        conditions = [
            "o.tenant_id = :tenant_id",
            "o.order_type = 'delivery'",
        ]
        params: dict[str, Any] = {"tenant_id": self.tenant_id}

        if filters.platform and filters.platform in self.PLATFORMS:
            conditions.append("o.sales_channel_id = :platform")
            params["platform"] = filters.platform
        if filters.status:
            conditions.append("o.status = :status")
            params["status"] = filters.status
        if filters.store_id:
            conditions.append("o.store_id = :store_id")
            params["store_id"] = filters.store_id
        if filters.keyword:
            conditions.append(
                "(o.order_metadata->>'platform_order_id' ILIKE :kw "
                "OR o.customer_phone ILIKE :kw)"
            )
            params["kw"] = f"%{filters.keyword}%"
        if filters.date_from:
            conditions.append("o.created_at >= :date_from")
            params["date_from"] = filters.date_from
        if filters.date_to:
            conditions.append("o.created_at <= :date_to")
            params["date_to"] = filters.date_to

        where = " AND ".join(conditions)
        offset = (filters.page - 1) * filters.size

        total = await self.db.scalar(
            text(f"SELECT COUNT(*) FROM orders o WHERE {where}"), params
        )

        rows = (await self.db.execute(
            text(f"""
                SELECT o.id, o.tenant_id, o.store_id, o.sales_channel_id,
                       o.status, o.total_amount_fen, o.order_metadata,
                       o.created_at, o.updated_at
                FROM orders o WHERE {where}
                ORDER BY o.created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {**params, "limit": filters.size, "offset": offset},
        )).fetchall()

        total_count = total or 0

        return {
            "items": [_row_to_order_summary(r) for r in rows],
            "total": total_count,
            "page": filters.page,
            "size": filters.size,
        }

    async def get_order_detail(self, order_id: str) -> dict | None:
        row = (await self.db.execute(
            text("""
                SELECT o.* FROM orders o
                WHERE o.id = :oid AND o.tenant_id = :tid
                  AND o.order_type = 'delivery'
            """),
            {"oid": order_id, "tid": self.tenant_id},
        )).first()
        if not row:
            return None

        m = row._mapping
        meta = m.get("order_metadata") or {}
        platform = str(m.get("sales_channel_id") or "")

        return {
            "id": str(m["id"]),
            "platform": platform,
            "platform_order_id": meta.get("platform_order_id", ""),
            "status": m["status"],
            "total_amount_fen": m["total_amount_fen"],
            "customer_phone": m.get("customer_phone") or "",
            "delivery_address": meta.get("delivery_address", ""),
            "notes": meta.get("delivery_notes", ""),
            "items": meta.get("items", []),
            "created_at": str(m["created_at"]),
            "updated_at": str(m["updated_at"]),
        }

    async def get_stats(
        self, store_id: str = "", platform: str = ""
    ) -> dict:
        conditions = [
            "o.tenant_id = :tenant_id",
            "o.order_type = 'delivery'",
        ]
        params: dict[str, Any] = {"tenant_id": self.tenant_id}
        if platform and platform in self.PLATFORMS:
            conditions.append("o.sales_channel_id = :platform")
            params["platform"] = platform
        if store_id:
            conditions.append("o.store_id = :store_id")
            params["store_id"] = store_id

        where = " AND ".join(conditions)
        row = (await self.db.execute(
            text(f"""
                SELECT
                    COUNT(*) AS total_orders,
                    COALESCE(SUM(o.total_amount_fen), 0) AS total_amount_fen,
                    COUNT(*) FILTER (WHERE o.status = 'pending') AS pending,
                    COUNT(*) FILTER (WHERE o.status IN ('confirmed','preparing','ready')) AS active,
                    COUNT(*) FILTER (WHERE o.status = 'completed') AS completed,
                    COUNT(*) FILTER (WHERE o.status = 'cancelled') AS cancelled
                FROM orders o WHERE {where}
            """),
            params,
        )).first()
        m = row._mapping
        return {
            "total_orders": m["total_orders"],
            "total_amount_fen": m["total_amount_fen"],
            "pending": m["pending"],
            "active": m["active"],
            "completed": m["completed"],
            "cancelled": m["cancelled"],
        }


def _row_to_order_summary(row: Any) -> dict:
    m = row._mapping
    meta = m.get("order_metadata") or {}
    return {
        "id": str(m["id"]),
        "platform": str(m.get("sales_channel_id") or ""),
        "status": m["status"],
        "total_amount_fen": m["total_amount_fen"],
        "platform_order_id": meta.get("platform_order_id", ""),
        "customer_phone": m.get("customer_phone") or "",
        "created_at": str(m["created_at"]),
    }
