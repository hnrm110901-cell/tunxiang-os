"""StorePnlProjector — 门店实时P&L投影器（因果链④多品牌P&L）

消费事件：
  order.paid             → 累计营收/订单数/客单价
  payment.confirmed      → 支付方式分布
  member.recharged       → 储值充值（新增负债，不计收入）
  settlement.advance_consumed → 储值消费转收入
  channel.commission_calc → 扣减渠道佣金

维护视图：mv_store_pnl
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from ..projector import ProjectorBase


class StorePnlProjector(ProjectorBase):
    name = "store_pnl"
    event_types = {
        "order.paid",
        "payment.confirmed",
        "member.recharged",
        "settlement.advance_consumed",
        "channel.commission_calc",
    }

    async def handle(self, event: dict[str, Any], conn: object) -> None:
        store_id = event.get("store_id")
        if not store_id:
            return

        occurred_at = event["occurred_at"]
        if isinstance(occurred_at, str):
            occurred_at = datetime.fromisoformat(occurred_at)
        stat_date = occurred_at.date()

        payload = event.get("payload") or {}
        event_type = event["event_type"]

        # 确保行存在
        await conn.execute(  # type: ignore[union-attr]
            """
            INSERT INTO mv_store_pnl
                (tenant_id, store_id, stat_date, updated_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (tenant_id, store_id, stat_date) DO NOTHING
            """,
            self.tenant_id,
            UUID(str(store_id)),
            stat_date,
        )

        if event_type == "order.paid":
            final_fen = payload.get("final_amount_fen", 0)
            customer_id = payload.get("customer_id")
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_store_pnl
                SET gross_revenue_fen  = gross_revenue_fen + $4,
                    net_revenue_fen    = net_revenue_fen + $4,
                    gross_profit_fen   = gross_profit_fen + $4,
                    order_count        = order_count + 1,
                    customer_count     = customer_count + $5,
                    last_event_id      = $6,
                    updated_at         = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3
                """,
                self.tenant_id,
                UUID(str(store_id)),
                stat_date,
                final_fen,
                1 if customer_id else 0,
                UUID(str(event["event_id"])),
            )
            await _recalc_pnl_rates(conn, self.tenant_id, UUID(str(store_id)), stat_date)

        elif event_type == "member.recharged":
            amount_fen = payload.get("amount_fen", 0)
            gift_fen = payload.get("gift_amount_fen", 0)
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_store_pnl
                SET stored_value_new_fen = stored_value_new_fen + $4,
                    last_event_id        = $5,
                    updated_at           = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3
                """,
                self.tenant_id,
                UUID(str(store_id)),
                stat_date,
                amount_fen + gift_fen,
                UUID(str(event["event_id"])),
            )

        elif event_type == "settlement.advance_consumed":
            amount_fen = payload.get("amount_fen", 0)
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_store_pnl
                SET stored_value_consumed_fen = stored_value_consumed_fen + $4,
                    last_event_id             = $5,
                    updated_at                = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3
                """,
                self.tenant_id,
                UUID(str(store_id)),
                stat_date,
                amount_fen,
                UUID(str(event["event_id"])),
            )

        elif event_type == "channel.commission_calc":
            commission_fen = payload.get("commission_fen", 0)
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_store_pnl
                SET net_revenue_fen  = net_revenue_fen - $4,
                    gross_profit_fen = gross_profit_fen - $4,
                    last_event_id    = $5,
                    updated_at       = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3
                """,
                self.tenant_id,
                UUID(str(store_id)),
                stat_date,
                commission_fen,
                UUID(str(event["event_id"])),
            )
            await _recalc_pnl_rates(conn, self.tenant_id, UUID(str(store_id)), stat_date)


async def _recalc_pnl_rates(conn: object, tenant_id: UUID, store_id: UUID, stat_date) -> None:
    """重算毛利率 + 客单价。"""
    await conn.execute(  # type: ignore[union-attr]
        """
        UPDATE mv_store_pnl
        SET gross_margin_rate = CASE
                WHEN net_revenue_fen > 0
                THEN ROUND(gross_profit_fen::NUMERIC / net_revenue_fen, 4)
                ELSE 0
            END,
            avg_check_fen = CASE
                WHEN order_count > 0
                THEN gross_revenue_fen / order_count
                ELSE 0
            END
        WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3
        """,
        tenant_id,
        store_id,
        stat_date,
    )
