"""DailySettlementProjector — 日清日结状态投影器（因果链⑦）

消费事件：
  payment.confirmed         → 按支付方式分类累计到账金额
  payment.cash_declared     → 现金申报，对比系统现金
  settlement.daily_closed   → 日结完成，更新状态
  settlement.reconciled     → 对账完成
  settlement.discrepancy_found → 差异发现，写入待确认列表

维护视图：mv_daily_settlement
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from ..projector import ProjectorBase


class DailySettlementProjector(ProjectorBase):
    name = "daily_settlement"
    event_types = {
        "payment.confirmed",
        "payment.cash_declared",
        "settlement.daily_closed",
        "settlement.reconciled",
        "settlement.discrepancy_found",
        "settlement.advance_consumed",
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
            INSERT INTO mv_daily_settlement
                (tenant_id, store_id, stat_date, status, updated_at)
            VALUES ($1, $2, $3, 'open', NOW())
            ON CONFLICT (tenant_id, store_id, stat_date) DO NOTHING
            """,
            self.tenant_id,
            UUID(str(store_id)),
            stat_date,
        )

        if event_type == "payment.confirmed":
            amount_fen = payload.get("amount_fen", 0)
            channel = payload.get("channel", "unknown")

            col_map = {
                "wechat": "wechat_received_fen",
                "alipay": "alipay_received_fen",
                "card": "card_received_fen",
                "cash": "wechat_received_fen",  # 现金单独由 cash_declared 处理，此处归其他
            }
            col = col_map.get(channel, "wechat_received_fen")

            await conn.execute(  # type: ignore[union-attr]
                f"""
                UPDATE mv_daily_settlement
                SET {col}            = {col} + $4,
                    total_revenue_fen = total_revenue_fen + $4,
                    last_event_id    = $5,
                    updated_at       = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3
                """,
                self.tenant_id,
                UUID(str(store_id)),
                stat_date,
                amount_fen,
                UUID(str(event["event_id"])),
            )

        elif event_type == "payment.cash_declared":
            declared_fen = payload.get("declared_fen", 0)
            system_fen = payload.get("system_fen", 0)
            discrepancy = declared_fen - system_fen
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_daily_settlement
                SET cash_declared_fen    = $4,
                    cash_system_fen      = $5,
                    cash_discrepancy_fen = $6,
                    last_event_id        = $7,
                    updated_at           = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3
                """,
                self.tenant_id,
                UUID(str(store_id)),
                stat_date,
                declared_fen,
                system_fen,
                discrepancy,
                UUID(str(event["event_id"])),
            )

        elif event_type == "settlement.advance_consumed":
            amount_fen = payload.get("amount_fen", 0)
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_daily_settlement
                SET stored_value_consumed_fen = stored_value_consumed_fen + $4,
                    total_revenue_fen          = total_revenue_fen + $4,
                    last_event_id              = $5,
                    updated_at                 = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3
                """,
                self.tenant_id,
                UUID(str(store_id)),
                stat_date,
                amount_fen,
                UUID(str(event["event_id"])),
            )

        elif event_type == "settlement.daily_closed":
            operator_id = payload.get("operator_id")
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_daily_settlement
                SET status        = 'closed',
                    closed_at     = $4,
                    closed_by     = $5,
                    last_event_id = $6,
                    updated_at    = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3
                """,
                self.tenant_id,
                UUID(str(store_id)),
                stat_date,
                occurred_at,
                UUID(str(operator_id)) if operator_id else None,
                UUID(str(event["event_id"])),
            )

        elif event_type == "settlement.discrepancy_found":
            item = {
                "type": payload.get("discrepancy_type", "unknown"),
                "amount_fen": payload.get("amount_fen", 0),
                "description": payload.get("description", ""),
            }
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_daily_settlement
                SET status        = 'discrepancy',
                    pending_items = pending_items || $4::jsonb,
                    last_event_id = $5,
                    updated_at    = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3
                """,
                self.tenant_id,
                UUID(str(store_id)),
                stat_date,
                json.dumps([item]),
                UUID(str(event["event_id"])),
            )

        elif event_type == "settlement.reconciled":
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_daily_settlement
                SET status        = 'closed',
                    last_event_id = $4,
                    updated_at    = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3
                """,
                self.tenant_id,
                UUID(str(store_id)),
                stat_date,
                UUID(str(event["event_id"])),
            )
