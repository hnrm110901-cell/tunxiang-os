"""EmployeeEfficiencyProjector — 人效指标物化视图投影器

消费事件：order.* + shift.* + scheduling.* 事件
维护视图：mv_employee_efficiency
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

import structlog

from ..projector import ProjectorBase

logger = structlog.get_logger(__name__)


class EmployeeEfficiencyProjector(ProjectorBase):
    """人效投影器 — 维护 mv_employee_efficiency 视图"""

    name = "employee_efficiency"
    event_types = {
        "order.paid",
        "order.served",
        "shift.started",
        "shift.ended",
        "employee.clock_in",
        "employee.clock_out",
        "service.rated",
    }

    async def handle(self, event: dict[str, Any], conn: object) -> None:
        event_type = event["event_type"]
        store_id = event.get("store_id")
        employee_id = event.get("employee_id") or event.get("payload", {}).get("employee_id")
        if not store_id or not employee_id:
            return

        occurred_at = event["occurred_at"]
        if isinstance(occurred_at, str):
            occurred_at = datetime.fromisoformat(occurred_at)
        stat_date = occurred_at.date()

        tid = self.tenant_id
        sid = UUID(str(store_id))
        eid = UUID(str(event["event_id"]))
        emp_id = UUID(str(employee_id))

        # Ensure row exists
        await conn.execute(
            """
            INSERT INTO mv_employee_efficiency (tenant_id, store_id, employee_id, stat_date, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (tenant_id, store_id, employee_id, stat_date) DO NOTHING
            """,
            tid, sid, emp_id, stat_date,
        )

        payload = event.get("payload") or {}

        if event_type == "order.paid":
            revenue_fen = payload.get("total_fen", 0)
            tip_fen = payload.get("tip_fen", 0)

            await conn.execute(
                """
                UPDATE mv_employee_efficiency
                SET orders_handled = orders_handled + 1,
                    revenue_contributed_fen = revenue_contributed_fen + $5,
                    tips_fen = tips_fen + $6,
                    last_event_id = $4,
                    updated_at = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND employee_id = $3 AND stat_date = $7
                """,
                tid, sid, emp_id, eid,
                revenue_fen, tip_fen, stat_date,
            )

        elif event_type == "order.served":
            service_time_sec = payload.get("service_time_sec", 0)
            if service_time_sec > 0:
                await conn.execute(
                    """
                    UPDATE mv_employee_efficiency
                    SET avg_service_time_sec = CASE
                        WHEN orders_handled > 0
                        THEN ((avg_service_time_sec * (orders_handled - 1) + $5) / orders_handled)::int
                        ELSE $5
                    END,
                        last_event_id = $4,
                        updated_at = NOW()
                    WHERE tenant_id = $1 AND store_id = $2 AND employee_id = $3 AND stat_date = $6
                    """,
                    tid, sid, emp_id, eid,
                    service_time_sec, stat_date,
                )

        elif event_type in ("shift.started", "employee.clock_in"):
            shift_hours = payload.get("planned_hours", 0) or 8
            role_type = payload.get("role_type", "") or payload.get("role", "")
            employee_name = payload.get("employee_name", "")

            await conn.execute(
                """
                UPDATE mv_employee_efficiency
                SET shift_hours = shift_hours + $5,
                    role_type = CASE WHEN $6 != '' THEN $6 ELSE role_type END,
                    employee_name = CASE WHEN $7 != '' THEN $7 ELSE employee_name END,
                    last_event_id = $4,
                    updated_at = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND employee_id = $3 AND stat_date = $8
                """,
                tid, sid, emp_id, eid,
                shift_hours, role_type, employee_name, stat_date,
            )

        elif event_type == "service.rated":
            rating = payload.get("rating", 5)
            has_error = payload.get("had_error", False) or payload.get("complaint", False)

            await conn.execute(
                """
                UPDATE mv_employee_efficiency
                SET efficiency_score = ROUND(
                    (efficiency_score * 0.7 + $5 * 0.3)::numeric, 2),
                    error_incidents = error_incidents + $6,
                    last_event_id = $4,
                    updated_at = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND employee_id = $3 AND stat_date = $7
                """,
                tid, sid, emp_id, eid,
                rating * 20.0,  # Normalize rating 1-5 to 0-100
                1 if has_error else 0,
                stat_date,
            )

        # Recalculate composite efficiency score after each event
        await _recalc_efficiency(conn, tid, sid, emp_id, stat_date)


async def _recalc_efficiency(conn, tid, sid, emp_id, stat_date):
    """Recalculate composite efficiency score."""
    await conn.execute(
        """
        UPDATE mv_employee_efficiency
        SET efficiency_score = ROUND(
            (CASE
                WHEN shift_hours > 0
                THEN (revenue_contributed_fen::NUMERIC / shift_hours / 100.0)
                ELSE 0
            END * 0.5 +
            CASE
                WHEN orders_handled > 0 AND avg_service_time_sec > 0
                THEN GREATEST(0, 100 - (avg_service_time_sec::NUMERIC / 60.0))
                ELSE 50
            END * 0.3 +
            CASE
                WHEN error_incidents = 0 THEN 100
                WHEN orders_handled > 0
                THEN GREATEST(0, 100 - (error_incidents::NUMERIC / orders_handled * 200))
                ELSE 50
            END * 0.2
        )::numeric, 2),
            attendance_score = ROUND(
                CASE
                    WHEN shift_hours >= 8 THEN 100
                    ELSE ROUND((shift_hours / 8.0 * 100)::numeric, 2)
                END, 2
            ),
            updated_at = NOW()
        WHERE tenant_id = $1 AND store_id = $2 AND employee_id = $3 AND stat_date = $4
        """,
        tid, sid, emp_id, stat_date,
    )
