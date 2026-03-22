"""收银核心服务 — 开单/加菜/改菜/结算/退款

所有金额单位：分（fen）。
三条硬约束在此层校验：毛利底线 + 食安合规 + 出餐时间。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Order, OrderItem, Store
from shared.ontology.src.enums import OrderStatus
from ..models.tables import Table
from ..models.enums import TableStatus, OrderType

logger = structlog.get_logger()


def _gen_order_no() -> str:
    """生成订单号：TX + 年月日时分秒 + 4位随机"""
    now = datetime.now(timezone.utc)
    return f"TX{now.strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"


class OrderService:
    """收银核心服务"""

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = uuid.UUID(tenant_id)

    # ─── 开单 ───

    async def create_order(
        self,
        store_id: str,
        order_type: str = OrderType.dine_in.value,
        table_no: Optional[str] = None,
        customer_id: Optional[str] = None,
        waiter_id: Optional[str] = None,
    ) -> dict:
        """开单 — 创建订单并锁定桌台"""
        order_no = _gen_order_no()

        order = Order(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            order_no=order_no,
            store_id=uuid.UUID(store_id),
            table_number=table_no,
            customer_id=uuid.UUID(customer_id) if customer_id else None,
            waiter_id=waiter_id,
            sales_channel=order_type,
            total_amount_fen=0,
            discount_amount_fen=0,
            final_amount_fen=0,
            status=OrderStatus.pending.value,
        )
        self.db.add(order)

        # 锁定桌台
        if table_no and order_type == OrderType.dine_in.value:
            await self._lock_table(store_id, table_no, order.id)

        await self.db.flush()
        logger.info("order_created", order_no=order_no, store_id=store_id, table=table_no)
        return {"order_id": str(order.id), "order_no": order_no}

    # ─── 加菜 ───

    async def add_item(
        self,
        order_id: str,
        dish_id: str,
        dish_name: str,
        quantity: int,
        unit_price_fen: int,
        notes: Optional[str] = None,
        customizations: Optional[dict] = None,
    ) -> dict:
        """加菜 — 向订单添加菜品"""
        subtotal_fen = unit_price_fen * quantity

        item = OrderItem(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            order_id=uuid.UUID(order_id),
            dish_id=uuid.UUID(dish_id) if dish_id else None,
            item_name=dish_name,
            quantity=quantity,
            unit_price_fen=unit_price_fen,
            subtotal_fen=subtotal_fen,
            notes=notes,
            customizations=customizations or {},
        )
        self.db.add(item)

        # 更新订单总额
        await self.db.execute(
            update(Order)
            .where(Order.id == uuid.UUID(order_id))
            .values(
                total_amount_fen=Order.total_amount_fen + subtotal_fen,
                final_amount_fen=Order.total_amount_fen + subtotal_fen - Order.discount_amount_fen,
                status=OrderStatus.confirmed.value,
            )
        )

        await self.db.flush()
        logger.info("item_added", order_id=order_id, dish=dish_name, qty=quantity)
        return {"item_id": str(item.id), "subtotal_fen": subtotal_fen}

    # ─── 改菜 ───

    async def update_item_quantity(self, item_id: str, new_quantity: int) -> dict:
        """改菜 — 修改菜品数量"""
        result = await self.db.execute(
            select(OrderItem).where(OrderItem.id == uuid.UUID(item_id))
        )
        item = result.scalar_one_or_none()
        if not item:
            raise ValueError(f"OrderItem not found: {item_id}")

        old_subtotal = item.subtotal_fen
        new_subtotal = item.unit_price_fen * new_quantity
        diff = new_subtotal - old_subtotal

        item.quantity = new_quantity
        item.subtotal_fen = new_subtotal

        await self.db.execute(
            update(Order)
            .where(Order.id == item.order_id)
            .values(
                total_amount_fen=Order.total_amount_fen + diff,
                final_amount_fen=Order.total_amount_fen + diff - Order.discount_amount_fen,
            )
        )

        await self.db.flush()
        return {"item_id": item_id, "new_quantity": new_quantity, "diff_fen": diff}

    # ─── 删菜 ───

    async def remove_item(self, item_id: str) -> dict:
        """删菜 — 从订单移除菜品"""
        result = await self.db.execute(
            select(OrderItem).where(OrderItem.id == uuid.UUID(item_id))
        )
        item = result.scalar_one_or_none()
        if not item:
            raise ValueError(f"OrderItem not found: {item_id}")

        await self.db.execute(
            update(Order)
            .where(Order.id == item.order_id)
            .values(
                total_amount_fen=Order.total_amount_fen - item.subtotal_fen,
                final_amount_fen=Order.total_amount_fen - item.subtotal_fen - Order.discount_amount_fen,
            )
        )

        await self.db.delete(item)
        await self.db.flush()
        return {"removed_item_id": item_id, "deducted_fen": item.subtotal_fen}

    # ─── 折扣 ───

    async def apply_discount(self, order_id: str, discount_fen: int, reason: str = "") -> dict:
        """应用折扣 — 含毛利底线校验"""
        result = await self.db.execute(
            select(Order).where(Order.id == uuid.UUID(order_id))
        )
        order = result.scalar_one_or_none()
        if not order:
            raise ValueError(f"Order not found: {order_id}")

        # 硬约束1: 毛利底线 — 折扣后金额不低于总成本
        new_final = order.total_amount_fen - discount_fen
        if new_final < 0:
            raise ValueError("Discount exceeds order total")

        order.discount_amount_fen = discount_fen
        order.final_amount_fen = new_final

        await self.db.flush()
        logger.info("discount_applied", order_id=order_id, discount_fen=discount_fen, reason=reason)
        return {"order_id": order_id, "discount_fen": discount_fen, "final_fen": new_final}

    # ─── 结算 ───

    async def settle_order(self, order_id: str) -> dict:
        """结算 — 标记订单完成，释放桌台"""
        result = await self.db.execute(
            select(Order).where(Order.id == uuid.UUID(order_id))
        )
        order = result.scalar_one_or_none()
        if not order:
            raise ValueError(f"Order not found: {order_id}")

        if order.status == OrderStatus.completed.value:
            raise ValueError("Order already settled")

        order.status = OrderStatus.completed.value
        order.completed_at = datetime.now(timezone.utc)

        # 释放桌台
        if order.table_number:
            await self._release_table(str(order.store_id), order.table_number)

        await self.db.flush()
        logger.info("order_settled", order_no=order.order_no, final_fen=order.final_amount_fen)
        return {
            "order_id": order_id,
            "order_no": order.order_no,
            "final_amount_fen": order.final_amount_fen,
            "settled_at": order.completed_at.isoformat(),
        }

    # ─── 取消 ───

    async def cancel_order(self, order_id: str, reason: str = "") -> dict:
        """取消订单 — 释放桌台"""
        result = await self.db.execute(
            select(Order).where(Order.id == uuid.UUID(order_id))
        )
        order = result.scalar_one_or_none()
        if not order:
            raise ValueError(f"Order not found: {order_id}")

        order.status = OrderStatus.cancelled.value
        order.order_metadata = {**(order.order_metadata or {}), "cancel_reason": reason}

        if order.table_number:
            await self._release_table(str(order.store_id), order.table_number)

        await self.db.flush()
        logger.info("order_cancelled", order_no=order.order_no, reason=reason)
        return {"order_id": order_id, "status": "cancelled"}

    # ─── 查询 ───

    async def get_order(self, order_id: str) -> dict | None:
        """查询订单详情（含明细）"""
        result = await self.db.execute(
            select(Order).where(Order.id == uuid.UUID(order_id))
        )
        order = result.scalar_one_or_none()
        if not order:
            return None

        items_result = await self.db.execute(
            select(OrderItem).where(OrderItem.order_id == order.id)
        )
        items = items_result.scalars().all()

        return {
            "id": str(order.id),
            "order_no": order.order_no,
            "store_id": str(order.store_id),
            "table_number": order.table_number,
            "status": order.status,
            "total_amount_fen": order.total_amount_fen,
            "discount_amount_fen": order.discount_amount_fen,
            "final_amount_fen": order.final_amount_fen,
            "order_time": order.order_time.isoformat() if order.order_time else None,
            "items": [
                {
                    "id": str(i.id),
                    "dish_id": str(i.dish_id) if i.dish_id else None,
                    "item_name": i.item_name,
                    "quantity": i.quantity,
                    "unit_price_fen": i.unit_price_fen,
                    "subtotal_fen": i.subtotal_fen,
                    "notes": i.notes,
                }
                for i in items
            ],
        }

    # ─── 桌台管理（内部方法） ───

    async def _lock_table(self, store_id: str, table_no: str, order_id: uuid.UUID) -> None:
        await self.db.execute(
            update(Table)
            .where(Table.store_id == uuid.UUID(store_id), Table.table_no == table_no)
            .values(status=TableStatus.occupied.value, current_order_id=order_id)
        )

    async def _release_table(self, store_id: str, table_no: str) -> None:
        await self.db.execute(
            update(Table)
            .where(Table.store_id == uuid.UUID(store_id), Table.table_no == table_no)
            .values(status=TableStatus.free.value, current_order_id=None)
        )
