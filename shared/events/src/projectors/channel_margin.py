"""ChannelMarginProjector — 渠道真实毛利投影器（因果链②）

消费事件：
  channel.order_synced      → 累计渠道GMV
  channel.commission_calc   → 计入平台佣金
  channel.promotion_applied → 计入平台补贴（正向收入）
  channel.settlement        → 最终结算到账确认

维护视图：mv_channel_margin
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from ..projector import ProjectorBase


class ChannelMarginProjector(ProjectorBase):
    name = "channel_margin"
    event_types = {
        "channel.order_synced",
        "channel.commission_calc",
        "channel.promotion_applied",
        "channel.settlement",
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
        channel = payload.get("channel", "unknown")
        event_type = event["event_type"]

        # 确保行存在
        await conn.execute(  # type: ignore[union-attr]
            """
            INSERT INTO mv_channel_margin
                (tenant_id, store_id, stat_date, channel, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (tenant_id, store_id, stat_date, channel) DO NOTHING
            """,
            self.tenant_id,
            UUID(str(store_id)),
            stat_date,
            channel,
        )

        if event_type == "channel.order_synced":
            amount_fen = payload.get("amount_fen", 0)
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_channel_margin
                SET gross_revenue_fen = gross_revenue_fen + $4,
                    order_count       = order_count + 1,
                    last_event_id     = $5,
                    updated_at        = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3 AND channel = $6
                """,
                self.tenant_id,
                UUID(str(store_id)),
                stat_date,
                amount_fen,
                UUID(str(event["event_id"])),
                channel,
            )

        elif event_type == "channel.commission_calc":
            commission_fen = payload.get("commission_fen", 0)
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_channel_margin
                SET commission_fen = commission_fen + $4,
                    last_event_id  = $5,
                    updated_at     = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3 AND channel = $6
                """,
                self.tenant_id,
                UUID(str(store_id)),
                stat_date,
                commission_fen,
                UUID(str(event["event_id"])),
                channel,
            )

        elif event_type == "channel.promotion_applied":
            subsidy_fen = payload.get("subsidy_fen", 0)
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_channel_margin
                SET promotion_subsidy_fen = promotion_subsidy_fen + $4,
                    last_event_id         = $5,
                    updated_at            = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3 AND channel = $6
                """,
                self.tenant_id,
                UUID(str(store_id)),
                stat_date,
                subsidy_fen,
                UUID(str(event["event_id"])),
                channel,
            )

        # 每次更新后重算净收入和毛利率
        await _recalc_margin(conn, self.tenant_id, UUID(str(store_id)), stat_date, channel)


async def _recalc_margin(conn: object, tenant_id: UUID, store_id: UUID, stat_date, channel: str) -> None:
    """重算净收入 = GMV - 佣金 + 补贴，毛利 = 净收入 - 食材成本。"""
    await conn.execute(  # type: ignore[union-attr]
        """
        UPDATE mv_channel_margin
        SET net_revenue_fen   = gross_revenue_fen - commission_fen + promotion_subsidy_fen,
            gross_margin_fen  = (gross_revenue_fen - commission_fen + promotion_subsidy_fen) - cogs_fen,
            gross_margin_rate = CASE
                WHEN (gross_revenue_fen - commission_fen + promotion_subsidy_fen) > 0
                THEN ROUND(
                    ((gross_revenue_fen - commission_fen + promotion_subsidy_fen) - cogs_fen)::NUMERIC
                    / (gross_revenue_fen - commission_fen + promotion_subsidy_fen),
                    4)
                ELSE 0
            END
        WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3 AND channel = $4
        """,
        tenant_id,
        store_id,
        stat_date,
        channel,
    )
