"""CustomerLtvProjector — 客户生命周期价值物化视图投影器

消费事件：order.* + member.* 事件
维护视图：mv_customer_ltv

This extends the existing mv_member_clv (which focuses on member CLV aggregation)
with per-customer LTV computation including churn risk and LTV tiering.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

import structlog

from ..projector import ProjectorBase

logger = structlog.get_logger(__name__)


class CustomerLtvProjector(ProjectorBase):
    """客户 LTV 投影器 — 维护 mv_customer_ltv 视图"""

    name = "customer_ltv"
    event_types = {
        "order.paid",
        "order.refunded",
        "member.registered",
        "member.level_changed",
        "member.last_visit_updated",
        "member.recharged",
    }

    async def handle(self, event: dict[str, Any], conn: object) -> None:
        event_type = event["event_type"]
        store_id = event.get("store_id")
        payload = event.get("payload") or {}

        customer_id = payload.get("customer_id")
        if not customer_id:
            return

        occurred_at = event["occurred_at"]
        if isinstance(occurred_at, str):
            occurred_at = datetime.fromisoformat(occurred_at)
        event_date = occurred_at.date()

        tid = self.tenant_id
        cid = UUID(str(customer_id))
        eid = UUID(str(event["event_id"]))

        # Ensure customer row exists
        await conn.execute(
            """
            INSERT INTO mv_customer_ltv (tenant_id, customer_id, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (tenant_id, customer_id) DO NOTHING
            """,
            tid, cid,
        )

        if event_type == "order.paid":
            total_fen = payload.get("total_fen", 0)
            channel = payload.get("channel", "")
            categories = payload.get("dish_categories", [])

            await conn.execute(
                """
                UPDATE mv_customer_ltv
                SET total_orders = total_orders + 1,
                    total_spent_fen = total_spent_fen + $3,
                    last_order_date = $4,
                    first_order_date = COALESCE(first_order_date, $4),
                    avg_order_value_fen = CASE
                        WHEN total_orders > 0
                        THEN ((total_spent_fen + $3) / (total_orders + 1))::bigint
                        ELSE $3
                    END,
                    preferred_channel = CASE
                        WHEN $5 != '' THEN $5
                        ELSE preferred_channel
                    END,
                    preferred_categories = _jsonb_merge_unique(preferred_categories, $6::jsonb),
                    last_event_id = $7,
                    updated_at = NOW()
                WHERE tenant_id = $1 AND customer_id = $2
                """,
                tid, cid, total_fen, event_date, channel,
                json.dumps(categories if isinstance(categories, list) else []),
                eid,
            )

            # Recalculate visit frequency
            await _recalc_visit_frequency(conn, tid, cid)

        elif event_type == "member.registered":
            customer_name = payload.get("customer_name", "") or payload.get("name", "")
            await conn.execute(
                """
                UPDATE mv_customer_ltv
                SET customer_name = CASE WHEN $3 != '' THEN $3 ELSE customer_name END,
                    first_order_date = COALESCE(first_order_date, $4),
                    last_event_id = $5,
                    updated_at = NOW()
                WHERE tenant_id = $1 AND customer_id = $2
                """,
                tid, cid, customer_name, event_date, eid,
            )

        elif event_type == "member.level_changed":
            new_level = payload.get("new_level", "regular")
            await conn.execute(
                """
                UPDATE mv_customer_ltv
                SET member_level = $3,
                    last_event_id = $4,
                    updated_at = NOW()
                WHERE tenant_id = $1 AND customer_id = $2
                """,
                tid, cid, new_level, eid,
            )

        elif event_type == "member.recharged":
            amount_fen = payload.get("amount_fen", 0)
            if amount_fen > 0:
                # Update total spent to include recharge when calculating LTV
                await conn.execute(
                    """
                    UPDATE mv_customer_ltv
                    SET predicted_ltv_fen = predicted_ltv_fen + $3,
                        last_event_id = $4,
                        updated_at = NOW()
                    WHERE tenant_id = $1 AND customer_id = $2
                    """,
                    tid, cid, amount_fen, eid,
                )

        # Recalculate churn risk and LTV tier after each event
        await _recalc_churn(conn, tid, cid)
        await _recalc_ltv_tier(conn, tid, cid)


async def _recalc_visit_frequency(conn, tid, cid):
    """Update visit frequency based on first/last order dates."""
    await conn.execute(
        """
        UPDATE mv_customer_ltv
        SET visit_frequency_days = CASE
            WHEN first_order_date IS NOT NULL AND last_order_date IS NOT NULL
                AND total_orders > 1
            THEN ROUND(
                (last_order_date - first_order_date)::NUMERIC / GREATEST(1, total_orders - 1), 2
            )
            ELSE 0
        END,
            updated_at = NOW()
        WHERE tenant_id = $1 AND customer_id = $2
        """,
        tid, cid,
    )


async def _recalc_churn(conn, tid, cid):
    """Calculate churn risk based on days since last order.

    Risk factors:
    - 0-7 days:   < 0.05 (very low)
    - 7-14 days:  0.05-0.15
    - 14-30 days: 0.15-0.35
    - 30-60 days: 0.35-0.60
    - 60+ days:   > 0.60
    """
    await conn.execute(
        """
        UPDATE mv_customer_ltv
        SET churn_risk = CASE
            WHEN last_order_date IS NULL THEN 0.5
            WHEN CURRENT_DATE - last_order_date <= 7 THEN 0.03
            WHEN CURRENT_DATE - last_order_date <= 14 THEN
                ROUND(0.05 + (CURRENT_DATE - last_order_date - 7)::NUMERIC / 70, 4)
            WHEN CURRENT_DATE - last_order_date <= 30 THEN
                ROUND(0.15 + (CURRENT_DATE - last_order_date - 14)::NUMERIC / 160, 4)
            WHEN CURRENT_DATE - last_order_date <= 60 THEN
                ROUND(0.35 + (CURRENT_DATE - last_order_date - 30)::NUMERIC / 120, 4)
            ELSE
                LEAST(0.95, ROUND(0.60 + (CURRENT_DATE - last_order_date - 60)::NUMERIC / 365, 4))
        END,
            discount_sensitivity = CASE
                WHEN total_orders > 0
                THEN ROUND(
                    (SELECT COUNT(*) FROM profit_split_records r
                     JOIN orders o ON o.id = r.order_id
                     WHERE r.tenant_id = $1
                       AND o.customer_id = $2
                       AND r.status = 'settled')::NUMERIC
                    / GREATEST(1, total_orders), 4
                )
                ELSE 0
            END,
            updated_at = NOW()
        WHERE tenant_id = $1 AND customer_id = $2
        """,
        tid, cid,
    )


async def _recalc_ltv_tier(conn, tid, cid):
    """Recalculate LTV tier and predicted LTV.

    predicted_ltv_fen = avg_order_value * expected_remaining_visits
    expected_remaining_visits estimated from visit frequency and churn risk.
    """
    await conn.execute(
        """
        UPDATE mv_customer_ltv
        SET predicted_ltv_fen = ROUND(
            avg_order_value_fen::NUMERIC *
            GREATEST(1, CASE
                WHEN churn_risk < 0.1 THEN 24    -- ~2 years
                WHEN churn_risk < 0.2 THEN 18
                WHEN churn_risk < 0.4 THEN 12    -- ~1 year
                WHEN churn_risk < 0.6 THEN 6     -- ~6 months
                ELSE 2                             -- ~2 months
            END * CASE
                WHEN visit_frequency_days > 0
                THEN 365.0 / GREATEST(1, visit_frequency_days)
                ELSE 12
            END / 12)
        )::bigint,
            ltv_tier = CASE
                WHEN total_spent_fen >= 200000 THEN 'whale'      -- 2000+ yuan
                WHEN total_spent_fen >= 50000  THEN 'dolphin'    -- 500-2000 yuan
                WHEN total_spent_fen >= 10000  THEN 'regular'    -- 100-500 yuan
                WHEN total_spent_fen > 0       THEN 'light'      -- < 100 yuan
                ELSE 'new'
            END,
            updated_at = NOW()
        WHERE tenant_id = $1 AND customer_id = $2
        """,
        tid, cid,
    )
