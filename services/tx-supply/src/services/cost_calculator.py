"""理论耗料计算引擎

基于当前激活 BOM 版本 x 各原料最新采购价，计算菜品理论成本。
金额单位: 分(fen), int 类型。
"""
import uuid

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


class CostCalculator:
    """理论耗料计算引擎"""

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self._tenant_uuid = uuid.UUID(tenant_id)

    async def _set_tenant(self) -> None:
        """设置 RLS tenant context"""
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self.tenant_id},
        )

    # ─── 单品理论成本 ───

    async def calculate_dish_cost(self, dish_id: str) -> dict:
        """计算菜品理论成本

        逻辑:
        1. 找到菜品当前激活的 BOM 模板
        2. 遍历 BOM 明细, 取每个原料的最新采购单价
        3. 理论成本 = SUM(standard_qty * unit_cost_fen) / yield_rate

        Returns:
            {
                "dish_id": str,
                "bom_template_id": str | None,
                "bom_version": str | None,
                "yield_rate": float,
                "theoretical_cost_fen": int,
                "items": [
                    {
                        "ingredient_id": str,
                        "standard_qty": float,
                        "unit": str,
                        "unit_cost_fen": int | None,
                        "line_cost_fen": int,
                        "waste_factor": float,
                    }
                ]
            }
        """
        await self._set_tenant()

        dish_uuid = uuid.UUID(dish_id)

        # 1. 查找激活的 BOM 模板
        bom_result = await self.db.execute(
            text("""
                SELECT id, version, yield_rate
                FROM bom_templates
                WHERE dish_id = :dish_id
                  AND tenant_id = :tenant_id
                  AND is_active = true
                  AND is_deleted = false
                ORDER BY effective_date DESC
                LIMIT 1
            """),
            {"dish_id": dish_uuid, "tenant_id": self._tenant_uuid},
        )
        bom_row = bom_result.mappings().first()

        if not bom_row:
            log.warning("no_active_bom", dish_id=dish_id)
            return {
                "dish_id": dish_id,
                "bom_template_id": None,
                "bom_version": None,
                "yield_rate": 1.0,
                "theoretical_cost_fen": 0,
                "items": [],
            }

        bom_id = bom_row["id"]
        version = bom_row["version"]
        yield_rate = float(bom_row["yield_rate"]) if bom_row["yield_rate"] else 1.0

        # 2. 查询 BOM 明细 + 原料最新采购价
        items_result = await self.db.execute(
            text("""
                SELECT bi.ingredient_id,
                       bi.standard_qty,
                       bi.unit,
                       bi.unit_cost_fen AS bom_unit_cost_fen,
                       bi.waste_factor,
                       i.unit_price_fen AS ingredient_unit_price_fen
                FROM bom_items bi
                LEFT JOIN ingredients i
                  ON i.id = bi.ingredient_id
                  AND i.tenant_id = bi.tenant_id
                  AND i.is_deleted = false
                WHERE bi.bom_id = :bom_id
                  AND bi.tenant_id = :tenant_id
                  AND bi.is_deleted = false
            """),
            {"bom_id": bom_id, "tenant_id": self._tenant_uuid},
        )
        items_rows = items_result.mappings().all()

        # 3. 计算每行成本
        cost_items = []
        raw_total_fen = 0

        for row in items_rows:
            standard_qty = float(row["standard_qty"])
            waste_factor = float(row["waste_factor"]) if row["waste_factor"] else 0.0

            # 优先用 BOM 快照价, 回退用原料库最新价
            unit_cost = row["bom_unit_cost_fen"] or row["ingredient_unit_price_fen"]

            if unit_cost is not None:
                # 含损耗的实际用量: standard_qty * (1 + waste_factor)
                effective_qty = standard_qty * (1 + waste_factor)
                line_cost_fen = int(round(effective_qty * unit_cost))
            else:
                line_cost_fen = 0

            raw_total_fen += line_cost_fen

            cost_items.append({
                "ingredient_id": str(row["ingredient_id"]),
                "standard_qty": standard_qty,
                "unit": row["unit"],
                "unit_cost_fen": unit_cost,
                "line_cost_fen": line_cost_fen,
                "waste_factor": waste_factor,
            })

        # 除以出成率得到理论成本
        if yield_rate > 0:
            theoretical_cost_fen = int(round(raw_total_fen / yield_rate))
        else:
            theoretical_cost_fen = raw_total_fen

        log.info(
            "dish_cost_calculated",
            dish_id=dish_id,
            bom_version=version,
            theoretical_cost_fen=theoretical_cost_fen,
            item_count=len(cost_items),
        )

        return {
            "dish_id": dish_id,
            "bom_template_id": str(bom_id),
            "bom_version": version,
            "yield_rate": yield_rate,
            "theoretical_cost_fen": theoretical_cost_fen,
            "items": cost_items,
        }

    # ─── 订单批量成本 ───

    async def calculate_order_cost(self, order_items: list[dict]) -> dict:
        """批量计算一个订单的理论成本

        Args:
            order_items: [{"dish_id": str, "quantity": int}, ...]

        Returns:
            {
                "total_theoretical_cost_fen": int,
                "per_item": [
                    {
                        "dish_id": str,
                        "quantity": int,
                        "unit_cost_fen": int,
                        "subtotal_cost_fen": int,
                    }
                ]
            }
        """
        total_cost_fen = 0
        per_item_results = []

        for oi in order_items:
            dish_id = oi["dish_id"]
            quantity = oi.get("quantity", 1)

            dish_cost = await self.calculate_dish_cost(dish_id)
            unit_cost_fen = dish_cost["theoretical_cost_fen"]
            subtotal_fen = unit_cost_fen * quantity
            total_cost_fen += subtotal_fen

            per_item_results.append({
                "dish_id": dish_id,
                "quantity": quantity,
                "unit_cost_fen": unit_cost_fen,
                "subtotal_cost_fen": subtotal_fen,
            })

        log.info(
            "order_cost_calculated",
            item_count=len(order_items),
            total_theoretical_cost_fen=total_cost_fen,
        )

        return {
            "total_theoretical_cost_fen": total_cost_fen,
            "per_item": per_item_results,
        }

    # ─── 成本分解明细 ───

    async def get_cost_breakdown(self, dish_id: str) -> dict:
        """成本分解明细 — 每个原料的成本占比

        Returns:
            {
                "dish_id": str,
                "theoretical_cost_fen": int,
                "breakdown": [
                    {
                        "ingredient_id": str,
                        "standard_qty": float,
                        "unit": str,
                        "unit_cost_fen": int | None,
                        "line_cost_fen": int,
                        "cost_ratio": float,  # 占比 0-1
                        "waste_factor": float,
                    }
                ]
            }
        """
        dish_cost = await self.calculate_dish_cost(dish_id)
        total = dish_cost["theoretical_cost_fen"]

        breakdown = []
        for item in dish_cost["items"]:
            ratio = item["line_cost_fen"] / total if total > 0 else 0.0
            breakdown.append({
                "ingredient_id": item["ingredient_id"],
                "standard_qty": item["standard_qty"],
                "unit": item["unit"],
                "unit_cost_fen": item["unit_cost_fen"],
                "line_cost_fen": item["line_cost_fen"],
                "cost_ratio": round(ratio, 4),
                "waste_factor": item["waste_factor"],
            })

        # 按占比降序
        breakdown.sort(key=lambda x: x["line_cost_fen"], reverse=True)

        return {
            "dish_id": dish_id,
            "bom_template_id": dish_cost.get("bom_template_id"),
            "bom_version": dish_cost.get("bom_version"),
            "theoretical_cost_fen": total,
            "breakdown": breakdown,
        }
