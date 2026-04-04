"""EnergyEfficiencyProjector — 能耗效率投影器（新模块⑨）

消费事件：
  energy.reading_captured   → IoT抄表数据，累计用量
  energy.anomaly_detected   → 异常能耗，计数+写入异常详情
  order.paid                → 关联营收（用于计算能耗/营收比）

维护视图：mv_energy_efficiency
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from ..projector import ProjectorBase


class EnergyEfficiencyProjector(ProjectorBase):

    name = "energy_efficiency"
    event_types = {
        "energy.reading_captured",
        "energy.anomaly_detected",
        "order.paid",
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
            INSERT INTO mv_energy_efficiency
                (tenant_id, store_id, stat_date, updated_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (tenant_id, store_id, stat_date) DO NOTHING
            """,
            self.tenant_id, UUID(str(store_id)), stat_date,
        )

        if event_type == "energy.reading_captured":
            electricity = float(payload.get("electricity_kwh", 0))
            gas = float(payload.get("gas_m3", 0))
            water = float(payload.get("water_ton", 0))
            cost_fen = int(payload.get("cost_fen", 0))
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_energy_efficiency
                SET electricity_kwh  = electricity_kwh + $4,
                    gas_m3           = gas_m3 + $5,
                    water_ton        = water_ton + $6,
                    energy_cost_fen  = energy_cost_fen + $7,
                    last_event_id    = $8,
                    updated_at       = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3
                """,
                self.tenant_id, UUID(str(store_id)), stat_date,
                electricity, gas, water, cost_fen,
                UUID(str(event["event_id"])),
            )
            await _recalc_ratio(conn, self.tenant_id, UUID(str(store_id)), stat_date)

        elif event_type == "energy.anomaly_detected":
            anomaly = {
                "type": payload.get("anomaly_type", "unknown"),
                "value": payload.get("value"),
                "threshold": payload.get("threshold"),
                "is_off_hours": payload.get("is_off_hours", False),
                "detected_at": occurred_at.isoformat(),
            }
            off_hours = [anomaly] if payload.get("is_off_hours") else []
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_energy_efficiency
                SET anomaly_count      = anomaly_count + 1,
                    off_hours_anomalies = off_hours_anomalies || $4::jsonb,
                    last_event_id       = $5,
                    updated_at          = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3
                """,
                self.tenant_id, UUID(str(store_id)), stat_date,
                json.dumps(off_hours), UUID(str(event["event_id"])),
            )

        elif event_type == "order.paid":
            final_fen = payload.get("final_amount_fen", 0)
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_energy_efficiency
                SET revenue_fen   = revenue_fen + $4,
                    last_event_id = $5,
                    updated_at    = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3
                """,
                self.tenant_id, UUID(str(store_id)), stat_date,
                final_fen, UUID(str(event["event_id"])),
            )
            await _recalc_ratio(conn, self.tenant_id, UUID(str(store_id)), stat_date)


async def _recalc_ratio(conn: object, tenant_id: UUID, store_id: UUID, stat_date) -> None:
    """能耗/营收比 = energy_cost_fen / revenue_fen。"""
    await conn.execute(  # type: ignore[union-attr]
        """
        UPDATE mv_energy_efficiency
        SET energy_revenue_ratio = CASE
            WHEN revenue_fen > 0
            THEN ROUND(energy_cost_fen::NUMERIC / revenue_fen, 4)
            ELSE 0
        END
        WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3
        """,
        tenant_id, store_id, stat_date,
    )
