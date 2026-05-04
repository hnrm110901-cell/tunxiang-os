"""DishProfitabilityProjector — 菜品盈利物化视图投影器

消费事件：order.item_ordered + menu.price_updated + channel.order_synced
维护视图：mv_dish_profitability
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

import structlog

from ..projector import ProjectorBase

logger = structlog.get_logger(__name__)


class DishProfitabilityProjector(ProjectorBase):
    """菜品盈利投影器 — 维护 mv_dish_profitability 视图"""

    name = "dish_profitability"
    event_types = {
        "order.item_ordered",
        "order.item_removed",
        "menu.price_updated",
        "channel.order_synced",
        "order.paid",
    }

    async def handle(self, event: dict[str, Any], conn: object) -> None:
        event_type = event["event_type"]
        store_id = event.get("store_id")
        if not store_id:
            return

        payload = event.get("payload") or {}
        dish_id_raw = payload.get("dish_id")
        if not dish_id_raw:
            return

        occurred_at = event["occurred_at"]
        if isinstance(occurred_at, str):
            occurred_at = datetime.fromisoformat(occurred_at)
        stat_date = occurred_at.date()

        tid = self.tenant_id
        sid = UUID(str(store_id))
        did = UUID(str(dish_id_raw))
        eid = UUID(str(event["event_id"]))

        # Ensure row exists
        await conn.execute(
            """
            INSERT INTO mv_dish_profitability (tenant_id, store_id, dish_id, stat_date, dish_name, updated_at)
            VALUES ($1, $2, $3, $4, '', NOW())
            ON CONFLICT (tenant_id, store_id, dish_id, stat_date) DO NOTHING
            """,
            tid, sid, did, stat_date,
        )

        if event_type == "order.item_ordered":
            quantity = payload.get("quantity", 1)
            unit_price_fen = payload.get("unit_price_fen", 0)
            discount_fen = payload.get("discount_fen", 0)
            bom_cost_fen = payload.get("bom_cost_fen", 0)
            channel_fee_fen = payload.get("channel_fee_fen", 0)
            dish_name = payload.get("dish_name", "")
            category = payload.get("category", "")

            gross = unit_price_fen * quantity
            net = gross - discount_fen
            margin = net - bom_cost_fen - channel_fee_fen

            await conn.execute(
                """
                UPDATE mv_dish_profitability
                SET order_count = order_count + $5,
                    gross_revenue_fen = gross_revenue_fen + $6,
                    discount_fen = discount_fen + $7,
                    net_revenue_fen = net_revenue_fen + $8,
                    bom_cost_fen = bom_cost_fen + $9,
                    channel_fee_fen = channel_fee_fen + $10,
                    gross_margin_fen = gross_margin_fen + $11,
                    dish_name = CASE WHEN $12 != '' THEN $12 ELSE dish_name END,
                    category = CASE WHEN $13 != '' THEN $13 ELSE category END,
                    last_event_id = $4,
                    updated_at = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND dish_id = $3 AND stat_date = $14
                """,
                tid, sid, did, eid,
                quantity, gross, discount_fen, net, bom_cost_fen, channel_fee_fen, margin,
                dish_name, category, stat_date,
            )

            # Recalculate margin rate
            await _recalc_margin(conn, tid, sid, did, stat_date)

        elif event_type == "order.item_removed":
            quantity = payload.get("quantity", 1)
            await conn.execute(
                """
                UPDATE mv_dish_profitability
                SET order_count = GREATEST(0, order_count - $5),
                    last_event_id = $4,
                    updated_at = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND dish_id = $3 AND stat_date = $6
                """,
                tid, sid, did, eid,
                quantity, stat_date,
            )

        elif event_type == "menu.price_updated":
            dish_name = payload.get("dish_name", "")
            await conn.execute(
                """
                UPDATE mv_dish_profitability
                SET dish_name = CASE WHEN $5 != '' THEN $5 ELSE dish_name END,
                    last_event_id = $4,
                    updated_at = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND dish_id = $3 AND stat_date = $6
                """,
                tid, sid, did, eid,
                dish_name, stat_date,
            )

        # Update ranking after each meaningful event
        if event_type in ("order.item_ordered", "order.paid"):
            await _update_rankings(conn, tid, sid, stat_date)


async def _recalc_margin(conn, tid, sid, did, stat_date):
    """Recalculate gross margin rate."""
    await conn.execute(
        """
        UPDATE mv_dish_profitability
        SET gross_margin_rate = CASE
            WHEN gross_revenue_fen > 0
            THEN ROUND(gross_margin_fen::NUMERIC / gross_revenue_fen, 4)
            ELSE 0
        END
        WHERE tenant_id = $1 AND store_id = $2 AND dish_id = $3 AND stat_date = $4
        """,
        tid, sid, did, stat_date,
    )


async def _update_rankings(conn, tid, sid, stat_date):
    """Update profitability and popularity rankings."""
    await conn.execute(
        """
        UPDATE mv_dish_profitability AS m
        SET profitability_rank = sub.profit_rank,
            popularity_rank = sub.pop_rank,
            recommendation_score = ROUND(
                (sub.profit_rank_frac * 0.6 + sub.pop_rank_frac * 0.4)::numeric, 2
            )
        FROM (
            SELECT tenant_id, store_id, dish_id, stat_date,
                RANK() OVER (ORDER BY gross_margin_rate DESC) AS profit_rank,
                RANK() OVER (ORDER BY order_count DESC) AS pop_rank,
                ROUND(
                    (RANK() OVER (ORDER BY gross_margin_rate DESC))::numeric /
                    GREATEST(1, COUNT(*) OVER ())::numeric, 2
                ) AS profit_rank_frac,
                ROUND(
                    (RANK() OVER (ORDER BY order_count DESC))::numeric /
                    GREATEST(1, COUNT(*) OVER ())::numeric, 2
                ) AS pop_rank_frac
            FROM mv_dish_profitability
            WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3
        ) AS sub
        WHERE m.tenant_id = sub.tenant_id
          AND m.store_id = sub.store_id
          AND m.dish_id = sub.dish_id
          AND m.stat_date = sub.stat_date
        """,
        tid, sid, stat_date,
    )
