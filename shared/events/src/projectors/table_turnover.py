"""TableTurnoverProjector — 翻台率物化视图投影器

消费事件：order.* + table_session.*
维护视图：mv_table_turnover
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

import structlog

from ..projector import ProjectorBase

logger = structlog.get_logger(__name__)


class TableTurnoverProjector(ProjectorBase):
    """翻台率投影器 — 维护 mv_table_turnover 视图"""

    name = "table_turnover"
    event_types = {
        "order.placed",
        "order.paid",
        "table.opened",
        "table.closed",
        "table.reserved",
    }

    async def handle(self, event: dict[str, Any], conn: object) -> None:
        event_type = event["event_type"]
        store_id = event.get("store_id")
        if not store_id:
            return

        occurred_at = event["occurred_at"]
        if isinstance(occurred_at, str):
            occurred_at = datetime.fromisoformat(occurred_at)
        stat_date = occurred_at.date()
        stat_hour = occurred_at.hour

        tid = self.tenant_id
        sid = UUID(str(store_id))
        eid = UUID(str(event["event_id"]))

        # Ensure daily row exists (hour=0 for daily summary)
        await conn.execute(
            """
            INSERT INTO mv_table_turnover (tenant_id, store_id, stat_date, stat_hour, updated_at)
            VALUES ($1, $2, $3, 0, NOW())
            ON CONFLICT (tenant_id, store_id, stat_date, stat_hour) DO NOTHING
            """,
            tid, sid, stat_date,
        )

        payload = event.get("payload") or {}

        if event_type == "table.opened":
            await conn.execute(
                """
                UPDATE mv_table_turnover
                SET occupied_tables = occupied_tables + 1,
                    last_event_id = $4,
                    updated_at = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3 AND stat_hour = 0
                """,
                tid, sid, stat_date, eid,
            )

        elif event_type == "table.closed":
            duration_mins = payload.get("duration_mins", 0)
            party_size = payload.get("party_size", 0)
            revenue_fen = payload.get("revenue_fen", 0)

            await conn.execute(
                """
                UPDATE mv_table_turnover
                SET turnover_count = turnover_count + 1,
                    occupied_tables = GREATEST(0, occupied_tables - 1),
                    avg_occupancy_mins = CASE
                        WHEN turnover_count > 0
                        THEN ((avg_occupancy_mins * turnover_count + $5) / (turnover_count + 1))::int
                        ELSE $5
                    END,
                    avg_party_size = CASE
                        WHEN turnover_count > 0
                        THEN ROUND(((avg_party_size * turnover_count + $6) / (turnover_count + 1))::numeric, 2)
                        ELSE $6
                    END,
                    revenue_per_table_fen = CASE
                        WHEN turnover_count > 0
                        THEN ((revenue_per_table_fen * turnover_count + $7) / (turnover_count + 1))::bigint
                        ELSE $7
                    END,
                    last_event_id = $4,
                    updated_at = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3 AND stat_hour = 0
                """,
                tid, sid, stat_date, eid,
                duration_mins, party_size, revenue_fen,
            )

        elif event_type == "order.paid":
            # Update peak hour tracking
            if stat_hour >= 11 and stat_hour <= 14:  # lunch peak
                await conn.execute(
                    """
                    INSERT INTO mv_table_turnover (tenant_id, store_id, stat_date, stat_hour, updated_at)
                    VALUES ($1, $2, $3, $4, NOW())
                    ON CONFLICT (tenant_id, store_id, stat_date, stat_hour) DO NOTHING
                    """,
                    tid, sid, stat_date, stat_hour,
                )
                await conn.execute(
                    """
                    UPDATE mv_table_turnover
                    SET peak_hour_tables = peak_hour_tables + 1,
                        last_event_id = $5,
                        updated_at = NOW()
                    WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3 AND stat_hour = $4
                    """,
                    tid, sid, stat_date, stat_hour, eid,
                )

        # Recalculate utilization rate after each event
        await conn.execute(
            """
            UPDATE mv_table_turnover
            SET table_utilization_rate = CASE
                WHEN total_tables > 0
                THEN ROUND(occupied_tables::NUMERIC / total_tables, 4)
                ELSE 0
            END,
                updated_at = NOW()
            WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3 AND stat_hour = 0
              AND occupied_tables != 0
            """,
            tid, sid, stat_date,
        )
