"""InventoryBomProjector — 库存BOM差异投影器（因果链③）

消费事件：
  inventory.consumed   → 记录BOM理论耗用（从 order.submitted 推算）
  inventory.received   → 入库
  inventory.wasted     → 损耗登记
  inventory.adjusted   → 盘点调整（差异 = actual - system）

维护视图：mv_inventory_bom
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from ..projector import ProjectorBase


class InventoryBomProjector(ProjectorBase):
    name = "inventory_bom"
    event_types = {
        "inventory.consumed",
        "inventory.received",
        "inventory.wasted",
        "inventory.adjusted",
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
        ingredient_id = payload.get("ingredient_id")
        if not ingredient_id:
            return

        ingredient_name = payload.get("ingredient_name", "")
        event_type = event["event_type"]

        # 确保行存在
        await conn.execute(  # type: ignore[union-attr]
            """
            INSERT INTO mv_inventory_bom
                (tenant_id, store_id, stat_date, ingredient_id, ingredient_name, updated_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
            ON CONFLICT (tenant_id, store_id, stat_date, ingredient_id) DO NOTHING
            """,
            self.tenant_id,
            UUID(str(store_id)),
            stat_date,
            UUID(str(ingredient_id)),
            ingredient_name,
        )

        quantity_g = float(payload.get("quantity_g", payload.get("quantity", 0)))

        if event_type == "inventory.consumed":
            # BOM 理论耗用（由下单推算）
            theoretical_g = float(payload.get("theoretical_g", quantity_g))
            actual_g = quantity_g
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_inventory_bom
                SET theoretical_usage_g = theoretical_usage_g + $4,
                    actual_usage_g      = actual_usage_g + $5,
                    last_event_id       = $6,
                    updated_at          = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3
                  AND ingredient_id = $7
                """,
                self.tenant_id,
                UUID(str(store_id)),
                stat_date,
                theoretical_g,
                actual_g,
                UUID(str(event["event_id"])),
                UUID(str(ingredient_id)),
            )

        elif event_type == "inventory.wasted":
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_inventory_bom
                SET waste_g       = waste_g + $4,
                    last_event_id = $5,
                    updated_at    = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3
                  AND ingredient_id = $6
                """,
                self.tenant_id,
                UUID(str(store_id)),
                stat_date,
                quantity_g,
                UUID(str(event["event_id"])),
                UUID(str(ingredient_id)),
            )

        # 重算未解释损耗率
        await _recalc_loss(conn, self.tenant_id, UUID(str(store_id)), stat_date, UUID(str(ingredient_id)))


async def _recalc_loss(conn: object, tenant_id: UUID, store_id: UUID, stat_date, ingredient_id: UUID) -> None:
    """未解释损耗 = 理论耗用 - 实际出库 - 登记损耗（可能为负=节省）"""
    await conn.execute(  # type: ignore[union-attr]
        """
        UPDATE mv_inventory_bom
        SET unexplained_loss_g = GREATEST(0, theoretical_usage_g - actual_usage_g - waste_g),
            loss_rate = CASE
                WHEN theoretical_usage_g > 0
                THEN ROUND((waste_g + GREATEST(0, theoretical_usage_g - actual_usage_g - waste_g))
                    / theoretical_usage_g, 4)
                ELSE 0
            END
        WHERE tenant_id = $1 AND store_id = $2 AND stat_date = $3 AND ingredient_id = $4
        """,
        tenant_id,
        store_id,
        stat_date,
        ingredient_id,
    )
