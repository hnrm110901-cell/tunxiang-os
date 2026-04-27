"""宴会原料分解服务 — 菜单BOM分解→库存核查→采购联动

核心: 宴会菜单 × 桌数 → BOM展开 → 现有库存扣减 → 生成采购清单。
对接: tx-supply采购系统 + 批次库存。
金额单位: 分(fen)。
"""

import json
import uuid
from datetime import date, datetime, timedelta, timezone

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


class BanquetMaterialService:
    """宴会原料分解"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id

    async def decompose_bom(self, banquet_id: str) -> dict:
        """菜单BOM分解: 菜品→原料"""
        row = await self.db.execute(
            text(
                "SELECT menu_json, table_count FROM banquets WHERE id = :bid AND tenant_id = :tid AND is_deleted = FALSE"
            ),
            {"bid": banquet_id, "tid": self.tenant_id},
        )
        banquet = row.mappings().first()
        if not banquet:
            raise ValueError(f"宴会不存在: {banquet_id}")

        menu = banquet["menu_json"] or []
        table_count = banquet["table_count"]
        if not menu:
            raise ValueError("菜单为空")

        # 收集所有菜品的BOM
        merged = {}  # ingredient_id → {name, category, qty, unit, cost}
        for dish in menu:
            dish_id = dish.get("product_id") or dish.get("dish_id")
            if not dish_id:
                continue

            # 查询菜品BOM (dish_ingredients表)
            bom_rows = await self.db.execute(
                text("""
                    SELECT di.ingredient_id, im.ingredient_name, im.category,
                           di.quantity, di.unit, im.unit_price_fen
                    FROM dish_ingredients di
                    JOIN ingredient_master im ON im.id = di.ingredient_id
                    WHERE di.dish_id = :did AND di.tenant_id = :tid AND di.is_deleted = FALSE
                """),
                {"did": dish_id, "tid": self.tenant_id},
            )
            for bom in bom_rows.mappings().all():
                iid = str(bom["ingredient_id"])
                needed = float(bom["quantity"] or 0) * table_count
                if iid in merged:
                    merged[iid]["required_qty"] += needed
                else:
                    merged[iid] = {
                        "ingredient_id": iid,
                        "ingredient_name": bom["ingredient_name"],
                        "category": bom["category"],
                        "required_qty": needed,
                        "unit": bom["unit"],
                        "unit_cost_fen": bom["unit_price_fen"] or 0,
                    }

        # 插入原料需求
        total_cost = 0
        items = []
        for iid, m in merged.items():
            cost = int(m["required_qty"] * m["unit_cost_fen"])
            total_cost += cost
            mid = str(uuid.uuid4())
            await self.db.execute(
                text("""
                    INSERT INTO banquet_material_requirements
                        (id, tenant_id, banquet_id, ingredient_id, ingredient_name,
                         category, required_qty, unit, unit_cost_fen, total_cost_fen, status)
                    VALUES (:id, :tid, :bid, :iid, :name,
                        :cat, :qty, :unit, :ucost, :tcost, 'calculated')
                """),
                {
                    "id": mid,
                    "tid": self.tenant_id,
                    "bid": banquet_id,
                    "iid": iid,
                    "name": m["ingredient_name"],
                    "cat": m["category"],
                    "qty": m["required_qty"],
                    "unit": m["unit"],
                    "ucost": m["unit_cost_fen"],
                    "tcost": cost,
                },
            )
            items.append({**m, "id": mid, "total_cost_fen": cost})

        await self.db.flush()
        logger.info("banquet_bom_decomposed", banquet_id=banquet_id, items=len(items), total_cost_fen=total_cost)
        return {"banquet_id": banquet_id, "total_items": len(items), "total_cost_fen": total_cost, "items": items}

    async def check_inventory(self, banquet_id: str) -> dict:
        """核查库存"""
        rows = await self.db.execute(
            text("""
                SELECT bmr.*, COALESCE(i.quantity, 0) AS stock_qty
                FROM banquet_material_requirements bmr
                LEFT JOIN ingredients i ON i.ingredient_id = bmr.ingredient_id AND i.tenant_id = bmr.tenant_id AND i.is_deleted = FALSE
                WHERE bmr.banquet_id = :bid AND bmr.tenant_id = :tid AND bmr.is_deleted = FALSE
            """),
            {"bid": banquet_id, "tid": self.tenant_id},
        )
        sufficient = []
        insufficient = []
        total_purchase_cost = 0

        for r in rows.mappings().all():
            item = dict(r)
            stock = float(item.get("stock_qty", 0))
            needed = float(item["required_qty"])
            item["inventory_available"] = stock
            purchase = max(0, needed - stock)
            item["purchase_needed"] = purchase

            if purchase > 0:
                source = "both" if stock > 0 else "purchase"
                item["source"] = source
                total_purchase_cost += int(purchase * item["unit_cost_fen"])
                insufficient.append(item)
            else:
                item["source"] = "inventory"
                sufficient.append(item)

            # 更新记录
            await self.db.execute(
                text("""
                    UPDATE banquet_material_requirements
                    SET inventory_available = :stock, purchase_needed = :purchase, source = :source, updated_at = NOW()
                    WHERE id = :id AND tenant_id = :tid
                """),
                {
                    "id": str(item["id"]),
                    "tid": self.tenant_id,
                    "stock": stock,
                    "purchase": purchase,
                    "source": item["source"],
                },
            )

        await self.db.flush()
        return {
            "banquet_id": banquet_id,
            "sufficient_count": len(sufficient),
            "insufficient_count": len(insufficient),
            "total_purchase_cost_fen": total_purchase_cost,
            "sufficient": sufficient,
            "insufficient": insufficient,
        }

    async def reserve_inventory(self, banquet_id: str) -> dict:
        """预留库存"""
        rows = await self.db.execute(
            text("""
                SELECT id, ingredient_id, required_qty, inventory_available, source
                FROM banquet_material_requirements
                WHERE banquet_id = :bid AND tenant_id = :tid AND status = 'calculated'
                  AND source IN ('inventory', 'both') AND is_deleted = FALSE
            """),
            {"bid": banquet_id, "tid": self.tenant_id},
        )
        reserved_count = 0
        for r in rows.mappings().all():
            reserve_qty = min(float(r["required_qty"]), float(r["inventory_available"]))
            await self.db.execute(
                text("""
                    UPDATE banquet_material_requirements
                    SET inventory_reserved = :rqty, status = 'reserved', updated_at = NOW()
                    WHERE id = :id AND tenant_id = :tid
                """),
                {"id": str(r["id"]), "tid": self.tenant_id, "rqty": reserve_qty},
            )
            reserved_count += 1

        await self.db.flush()
        logger.info("banquet_inventory_reserved", banquet_id=banquet_id, count=reserved_count)
        return {"banquet_id": banquet_id, "reserved_count": reserved_count}

    async def generate_purchase_order(
        self,
        banquet_id: str,
        supplier_id: str | None = None,
        required_by: date | None = None,
    ) -> dict:
        """生成采购单"""
        # 获取宴会信息
        brow = await self.db.execute(
            text(
                "SELECT store_id, event_date FROM banquets WHERE id = :bid AND tenant_id = :tid AND is_deleted = FALSE"
            ),
            {"bid": banquet_id, "tid": self.tenant_id},
        )
        banquet = brow.mappings().first()
        if not banquet:
            raise ValueError(f"宴会不存在: {banquet_id}")

        if not required_by:
            required_by = banquet["event_date"] - timedelta(days=2)

        # 收集需采购项
        rows = await self.db.execute(
            text("""
                SELECT id, ingredient_id, ingredient_name, purchase_needed, unit, unit_cost_fen
                FROM banquet_material_requirements
                WHERE banquet_id = :bid AND tenant_id = :tid AND purchase_needed > 0 AND is_deleted = FALSE
            """),
            {"bid": banquet_id, "tid": self.tenant_id},
        )
        items = []
        total_fen = 0
        req_ids = []
        for r in rows.mappings().all():
            subtotal = int(float(r["purchase_needed"]) * r["unit_cost_fen"])
            total_fen += subtotal
            items.append(
                {
                    "ingredient_id": str(r["ingredient_id"]) if r["ingredient_id"] else None,
                    "name": r["ingredient_name"],
                    "qty": float(r["purchase_needed"]),
                    "unit": r["unit"],
                    "unit_cost_fen": r["unit_cost_fen"],
                    "subtotal_fen": subtotal,
                }
            )
            req_ids.append(str(r["id"]))

        if not items:
            return {"banquet_id": banquet_id, "message": "无需采购"}

        po_no = f"BPO-{uuid.uuid4().hex[:12].upper()}"
        po_id = str(uuid.uuid4())

        await self.db.execute(
            text("""
                INSERT INTO banquet_purchase_orders
                    (id, tenant_id, po_no, banquet_id, store_id, supplier_id,
                     items_json, total_fen, required_by, status)
                VALUES (:id, :tid, :no, :bid, :sid, :supid,
                    :items::jsonb, :total, :rby, 'draft')
            """),
            {
                "id": po_id,
                "tid": self.tenant_id,
                "no": po_no,
                "bid": banquet_id,
                "sid": str(banquet["store_id"]),
                "supid": supplier_id,
                "items": json.dumps(items, ensure_ascii=False),
                "total": total_fen,
                "rby": required_by,
            },
        )

        # 关联采购单到原料需求
        for rid in req_ids:
            await self.db.execute(
                text(
                    "UPDATE banquet_material_requirements SET purchase_order_id = :poid, status = 'ordered', updated_at = NOW() WHERE id = :rid AND tenant_id = :tid"
                ),
                {"poid": po_id, "rid": rid, "tid": self.tenant_id},
            )

        await self.db.flush()
        logger.info("banquet_purchase_order_generated", po_no=po_no, items=len(items), total_fen=total_fen)
        return {
            "id": po_id,
            "po_no": po_no,
            "items_count": len(items),
            "total_fen": total_fen,
            "required_by": required_by.isoformat(),
            "status": "draft",
        }

    async def get_material_summary(self, banquet_id: str) -> dict:
        """原料汇总(按类别)"""
        rows = await self.db.execute(
            text("""
                SELECT category, COUNT(*) AS item_count, SUM(total_cost_fen) AS category_cost_fen
                FROM banquet_material_requirements
                WHERE banquet_id = :bid AND tenant_id = :tid AND is_deleted = FALSE
                GROUP BY category ORDER BY category_cost_fen DESC
            """),
            {"bid": banquet_id, "tid": self.tenant_id},
        )
        categories = [dict(r) for r in rows.mappings().all()]
        grand_total = sum(c.get("category_cost_fen", 0) or 0 for c in categories)
        return {"banquet_id": banquet_id, "categories": categories, "grand_total_fen": grand_total}

    async def update_purchase_status(self, po_id: str, new_status: str) -> dict:
        """更新采购单状态"""
        result = await self.db.execute(
            text("""
                UPDATE banquet_purchase_orders SET status = :status, updated_at = NOW()
                WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE
                RETURNING id, po_no
            """),
            {"id": po_id, "tid": self.tenant_id, "status": new_status},
        )
        row = result.mappings().first()
        if not row:
            raise ValueError(f"采购单不存在: {po_id}")
        await self.db.flush()
        return {"id": str(row["id"]), "po_no": row["po_no"], "status": new_status}

    async def get_purchase_orders(self, banquet_id: str) -> list:
        """获取宴会采购单列表"""
        rows = await self.db.execute(
            text(
                "SELECT * FROM banquet_purchase_orders WHERE banquet_id = :bid AND tenant_id = :tid AND is_deleted = FALSE ORDER BY created_at DESC"
            ),
            {"bid": banquet_id, "tid": self.tenant_id},
        )
        return [dict(r) for r in rows.mappings().all()]

    async def mark_received(self, po_id: str, received_items: list) -> dict:
        """标记到货"""
        now = datetime.now(timezone.utc)
        await self.db.execute(
            text(
                "UPDATE banquet_purchase_orders SET status = 'received', received_at = :now, updated_at = :now WHERE id = :id AND tenant_id = :tid"
            ),
            {"id": po_id, "tid": self.tenant_id, "now": now},
        )
        # 更新原料需求状态
        await self.db.execute(
            text(
                "UPDATE banquet_material_requirements SET status = 'received', updated_at = :now WHERE purchase_order_id = :poid AND tenant_id = :tid"
            ),
            {"poid": po_id, "tid": self.tenant_id, "now": now},
        )
        await self.db.flush()
        logger.info("banquet_purchase_received", po_id=po_id)
        return {"po_id": po_id, "status": "received"}
