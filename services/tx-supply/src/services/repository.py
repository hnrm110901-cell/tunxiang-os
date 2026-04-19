"""库存 Repository — 真实 DB 查询层

封装 Ingredient / IngredientTransaction 的查询与库存调整。
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Ingredient, IngredientTransaction
from shared.ontology.src.enums import InventoryStatus, TransactionType


class InventoryRepository:
    """库存 Repository — 封装真实 DB 查询"""

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self._tenant_uuid = uuid.UUID(tenant_id)

    async def _set_tenant(self) -> None:
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self.tenant_id},
        )

    # ─── 库存查询 ───

    async def list_inventory(
        self,
        store_id: str,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页查询库存列表"""
        await self._set_tenant()

        store_uuid = uuid.UUID(store_id)
        base = (
            select(Ingredient)
            .where(Ingredient.tenant_id == self._tenant_uuid)
            .where(Ingredient.store_id == store_uuid)
            .where(Ingredient.is_deleted == False)  # noqa: E712
        )
        count_base = (
            select(func.count(Ingredient.id))
            .where(Ingredient.tenant_id == self._tenant_uuid)
            .where(Ingredient.store_id == store_uuid)
            .where(Ingredient.is_deleted == False)  # noqa: E712
        )

        if status:
            base = base.where(Ingredient.status == status)
            count_base = count_base.where(Ingredient.status == status)

        total_result = await self.db.execute(count_base)
        total = total_result.scalar() or 0

        offset = (page - 1) * size
        query = base.order_by(Ingredient.ingredient_name).offset(offset).limit(size)
        result = await self.db.execute(query)
        rows = result.scalars().all()

        items = [self._ingredient_to_dict(i) for i in rows]
        return {"items": items, "total": total, "page": page, "size": size}

    # ─── 预警 ───

    async def get_alerts(self, store_id: str) -> list:
        """获取库存预警列表（低库存 + 临界状态）"""
        await self._set_tenant()

        store_uuid = uuid.UUID(store_id)
        result = await self.db.execute(
            select(Ingredient)
            .where(Ingredient.tenant_id == self._tenant_uuid)
            .where(Ingredient.store_id == store_uuid)
            .where(Ingredient.is_deleted == False)  # noqa: E712
            .where(
                Ingredient.status.in_(
                    [
                        InventoryStatus.low.value,
                        InventoryStatus.critical.value,
                        InventoryStatus.out_of_stock.value,
                    ]
                )
            )
            .order_by(
                case(
                    (Ingredient.status == InventoryStatus.out_of_stock.value, 0),
                    (Ingredient.status == InventoryStatus.critical.value, 1),
                    (Ingredient.status == InventoryStatus.low.value, 2),
                    else_=3,
                )
            )
        )
        rows = result.scalars().all()

        return [
            {
                "id": str(i.id),
                "ingredient_name": i.ingredient_name,
                "category": i.category,
                "current_quantity": i.current_quantity,
                "min_quantity": i.min_quantity,
                "unit": i.unit,
                "status": i.status,
                "alert_type": "out_of_stock"
                if i.status == InventoryStatus.out_of_stock.value
                else "critical"
                if i.status == InventoryStatus.critical.value
                else "low",
            }
            for i in rows
        ]

    # ─── 库存调整 ───

    async def adjust_inventory(self, item_id: str, quantity: float, reason: str) -> dict:
        """调整库存数量，同时记录流水"""
        await self._set_tenant()

        item_uuid = uuid.UUID(item_id)
        result = await self.db.execute(
            select(Ingredient)
            .where(Ingredient.id == item_uuid)
            .where(Ingredient.tenant_id == self._tenant_uuid)
            .where(Ingredient.is_deleted == False)  # noqa: E712
        )
        ingredient = result.scalar_one_or_none()
        if not ingredient:
            raise ValueError(f"Ingredient not found: {item_id}")

        old_quantity = ingredient.current_quantity
        new_quantity = old_quantity + quantity
        if new_quantity < 0:
            raise ValueError(f"Insufficient stock: current={old_quantity}, adjustment={quantity}")

        # 更新库存数量与状态
        new_status = self._calc_status(new_quantity, ingredient.min_quantity, ingredient.max_quantity)
        ingredient.current_quantity = new_quantity
        ingredient.status = new_status

        # 记录流水
        txn = IngredientTransaction(
            id=uuid.uuid4(),
            tenant_id=self._tenant_uuid,
            ingredient_id=item_uuid,
            transaction_type=TransactionType.adjustment.value,
            quantity=quantity,
            unit_cost_fen=ingredient.unit_price_fen,
            notes=reason,
        )
        self.db.add(txn)
        await self.db.flush()

        return {
            "id": str(ingredient.id),
            "ingredient_name": ingredient.ingredient_name,
            "old_quantity": old_quantity,
            "new_quantity": new_quantity,
            "adjustment": quantity,
            "status": new_status,
            "transaction_id": str(txn.id),
        }

    # ─── 损耗 Top5 ───

    async def get_waste_top5(self, store_id: str, period: str = "month") -> list:
        """获取损耗 Top5（按金额排序）"""
        await self._set_tenant()

        store_uuid = uuid.UUID(store_id)

        # 计算时间范围
        now = datetime.now(timezone.utc)
        if period == "week":
            since = now - timedelta(days=7)
        elif period == "month":
            since = now - timedelta(days=30)
        elif period == "quarter":
            since = now - timedelta(days=90)
        else:
            since = now - timedelta(days=30)

        result = await self.db.execute(
            select(
                Ingredient.ingredient_name,
                Ingredient.category,
                Ingredient.unit,
                func.sum(IngredientTransaction.quantity).label("total_waste_qty"),
                func.sum(IngredientTransaction.quantity * IngredientTransaction.unit_cost_fen).label("total_waste_fen"),
            )
            .join(IngredientTransaction, IngredientTransaction.ingredient_id == Ingredient.id)
            .where(Ingredient.tenant_id == self._tenant_uuid)
            .where(Ingredient.store_id == store_uuid)
            .where(IngredientTransaction.transaction_type == TransactionType.waste.value)
            .where(IngredientTransaction.created_at >= since)
            .group_by(Ingredient.ingredient_name, Ingredient.category, Ingredient.unit)
            .order_by(func.sum(IngredientTransaction.quantity * IngredientTransaction.unit_cost_fen).desc())
            .limit(5)
        )
        rows = result.all()

        return [
            {
                "ingredient_name": row[0],
                "category": row[1],
                "unit": row[2],
                "total_waste_qty": abs(float(row[3])) if row[3] else 0,
                "total_waste_fen": abs(int(row[4])) if row[4] else 0,
            }
            for row in rows
        ]

    # ─── 内部工具 ───

    @staticmethod
    def _calc_status(current: float, min_qty: float, max_qty: Optional[float]) -> str:
        if current <= 0:
            return InventoryStatus.out_of_stock.value
        if current <= min_qty * 0.3:
            return InventoryStatus.critical.value
        if current <= min_qty:
            return InventoryStatus.low.value
        return InventoryStatus.normal.value

    @staticmethod
    def _ingredient_to_dict(i: Ingredient) -> dict:
        return {
            "id": str(i.id),
            "store_id": str(i.store_id),
            "ingredient_name": i.ingredient_name,
            "category": i.category,
            "unit": i.unit,
            "current_quantity": i.current_quantity,
            "min_quantity": i.min_quantity,
            "max_quantity": i.max_quantity,
            "unit_price_fen": i.unit_price_fen,
            "status": i.status,
            "supplier_name": i.supplier_name,
            "created_at": i.created_at.isoformat() if i.created_at else None,
        }
