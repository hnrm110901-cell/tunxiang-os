"""MemberClvProjector — 会员生命周期价值投影器（因果链⑤）

消费事件：
  member.registered      → 初始化CLV记录
  member.recharged       → 储值充值（记为负债，不计CLV）
  member.consumed        → 储值消费（累计消费金额）
  member.voucher_used    → 券核销（记录券成本）
  order.paid             → 消费记录（visit_count+1，last_visit_at更新）
  member.churn_predicted → Agent预测结果写入

维护视图：mv_member_clv
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from ..projector import ProjectorBase


class MemberClvProjector(ProjectorBase):
    name = "member_clv"
    event_types = {
        "member.registered",
        "member.recharged",
        "member.consumed",
        "member.voucher_used",
        "order.paid",
        "member.churn_predicted",
    }

    async def handle(self, event: dict[str, Any], conn: object) -> None:
        payload = event.get("payload") or {}
        customer_id = payload.get("customer_id")
        if not customer_id:
            return

        event_type = event["event_type"]
        occurred_at = event["occurred_at"]
        if isinstance(occurred_at, str):
            occurred_at = datetime.fromisoformat(occurred_at)

        # 确保行存在
        await conn.execute(  # type: ignore[union-attr]
            """
            INSERT INTO mv_member_clv (tenant_id, customer_id, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (tenant_id, customer_id) DO NOTHING
            """,
            self.tenant_id,
            UUID(str(customer_id)),
        )

        if event_type == "order.paid":
            amount_fen = payload.get("final_amount_fen", 0)
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_member_clv
                SET total_spend_fen = total_spend_fen + $3,
                    visit_count     = visit_count + 1,
                    clv_fen         = clv_fen + $3,
                    last_visit_at   = $4,
                    last_event_id   = $5,
                    updated_at      = NOW()
                WHERE tenant_id = $1 AND customer_id = $2
                """,
                self.tenant_id,
                UUID(str(customer_id)),
                amount_fen,
                occurred_at,
                UUID(str(event["event_id"])),
            )

        elif event_type == "member.recharged":
            amount_fen = payload.get("amount_fen", 0)
            gift_fen = payload.get("gift_amount_fen", 0)
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_member_clv
                SET stored_value_balance_fen = stored_value_balance_fen + $3,
                    last_event_id            = $4,
                    updated_at               = NOW()
                WHERE tenant_id = $1 AND customer_id = $2
                """,
                self.tenant_id,
                UUID(str(customer_id)),
                amount_fen + gift_fen,
                UUID(str(event["event_id"])),
            )

        elif event_type == "member.consumed":
            amount_fen = payload.get("amount_fen", 0)
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_member_clv
                SET stored_value_balance_fen = GREATEST(0, stored_value_balance_fen - $3),
                    last_event_id            = $4,
                    updated_at               = NOW()
                WHERE tenant_id = $1 AND customer_id = $2
                """,
                self.tenant_id,
                UUID(str(customer_id)),
                amount_fen,
                UUID(str(event["event_id"])),
            )

        elif event_type == "member.voucher_used":
            voucher_cost_fen = payload.get("face_value_fen", 0)
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_member_clv
                SET voucher_used_count = voucher_used_count + 1,
                    voucher_cost_fen   = voucher_cost_fen + $3,
                    last_event_id      = $4,
                    updated_at         = NOW()
                WHERE tenant_id = $1 AND customer_id = $2
                """,
                self.tenant_id,
                UUID(str(customer_id)),
                voucher_cost_fen,
                UUID(str(event["event_id"])),
            )

        elif event_type == "member.churn_predicted":
            churn_prob = float(payload.get("churn_probability", 0))
            next_visit = payload.get("next_visit_days")
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_member_clv
                SET churn_probability = $3,
                    next_visit_days   = $4,
                    last_event_id     = $5,
                    updated_at        = NOW()
                WHERE tenant_id = $1 AND customer_id = $2
                """,
                self.tenant_id,
                UUID(str(customer_id)),
                churn_prob,
                next_visit,
                UUID(str(event["event_id"])),
            )
