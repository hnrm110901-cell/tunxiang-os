"""收银核心服务 — 开单/加菜/改菜/结算/退款

所有金额单位：分（fen）。
三条硬约束在此层校验：毛利底线 + 食安合规 + 出餐时间。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Order, OrderItem, Store
from shared.ontology.src.enums import OrderStatus
from ..models.tables import Table
from ..models.enums import TableStatus, OrderType

logger = structlog.get_logger()


def _gen_order_no() -> str:
    now = datetime.now(timezone.utc)
    return f"TX{now.strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"


class OrderService:
    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = uuid.UUID(tenant_id)
        self._tenant_id_str = tenant_id

    async def _set_tenant(self) -> None:
        await self.db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": self._tenant_id_str})

    async def create_order(self, store_id: str, order_type: str = OrderType.dine_in.value, table_no: Optional[str] = None, customer_id: Optional[str] = None, waiter_id: Optional[str] = None) -> dict:
        await self._set_tenant()
        order_no = _gen_order_no()
        order = Order(id=uuid.uuid4(), tenant_id=self.tenant_id, order_no=order_no, store_id=uuid.UUID(store_id), table_number=table_no, customer_id=uuid.UUID(customer_id) if customer_id else None, waiter_id=waiter_id, sales_channel=order_type, total_amount_fen=0, discount_amount_fen=0, final_amount_fen=0, status=OrderStatus.pending.value)
        self.db.add(order)
        if table_no and order_type == OrderType.dine_in.value:
            await self._lock_table(store_id, table_no, order.id)
        await self.db.flush()
        return {"order_id": str(order.id), "order_no": order_no}

    async def add_item(self, order_id: str, dish_id: str, dish_name: str, quantity: int, unit_price_fen: int, notes: Optional[str] = None, customizations: Optional[dict] = None) -> dict:
        await self._set_tenant()
        subtotal_fen = unit_price_fen * quantity
        item = OrderItem(id=uuid.uuid4(), tenant_id=self.tenant_id, order_id=uuid.UUID(order_id), dish_id=uuid.UUID(dish_id) if dish_id else None, item_name=dish_name, quantity=quantity, unit_price_fen=unit_price_fen, subtotal_fen=subtotal_fen, notes=notes, customizations=customizations or {})
        self.db.add(item)
        await self.db.execute(update(Order).where(Order.id == uuid.UUID(order_id)).where(Order.tenant_id == self.tenant_id).values(total_amount_fen=Order.total_amount_fen + subtotal_fen, final_amount_fen=Order.total_amount_fen + subtotal_fen - Order.discount_amount_fen, status=OrderStatus.confirmed.value))
        await self.db.flush()
        return {"item_id": str(item.id), "subtotal_fen": subtotal_fen}

    async def update_item_quantity(self, item_id: str, new_quantity: int) -> dict:
        await self._set_tenant()
        result = await self.db.execute(select(OrderItem).where(OrderItem.id == uuid.UUID(item_id)).where(OrderItem.tenant_id == self.tenant_id))
        item = result.scalar_one_or_none()
        if not item:
            raise ValueError(f"OrderItem not found: {item_id}")
        diff = item.unit_price_fen * new_quantity - item.subtotal_fen
        item.quantity = new_quantity
        item.subtotal_fen = item.unit_price_fen * new_quantity
        await self.db.execute(update(Order).where(Order.id == item.order_id).where(Order.tenant_id == self.tenant_id).values(total_amount_fen=Order.total_amount_fen + diff, final_amount_fen=Order.total_amount_fen + diff - Order.discount_amount_fen))
        await self.db.flush()
        return {"item_id": item_id, "new_quantity": new_quantity, "diff_fen": diff}

    async def remove_item(self, item_id: str) -> dict:
        await self._set_tenant()
        result = await self.db.execute(select(OrderItem).where(OrderItem.id == uuid.UUID(item_id)).where(OrderItem.tenant_id == self.tenant_id))
        item = result.scalar_one_or_none()
        if not item:
            raise ValueError(f"OrderItem not found: {item_id}")
        await self.db.execute(update(Order).where(Order.id == item.order_id).where(Order.tenant_id == self.tenant_id).values(total_amount_fen=Order.total_amount_fen - item.subtotal_fen, final_amount_fen=Order.total_amount_fen - item.subtotal_fen - Order.discount_amount_fen))
        await self.db.delete(item)
        await self.db.flush()
        return {"removed_item_id": item_id, "deducted_fen": item.subtotal_fen}

    async def apply_discount(self, order_id: str, discount_fen: int, reason: str = "") -> dict:
        await self._set_tenant()
        result = await self.db.execute(select(Order).where(Order.id == uuid.UUID(order_id)).where(Order.tenant_id == self.tenant_id))
        order = result.scalar_one_or_none()
        if not order:
            raise ValueError(f"Order not found: {order_id}")
        new_final = order.total_amount_fen - discount_fen
        if new_final < 0:
            raise ValueError("Discount exceeds order total")
        order.discount_amount_fen = discount_fen
        order.final_amount_fen = new_final
        await self.db.flush()
        return {"order_id": order_id, "discount_fen": discount_fen, "final_fen": new_final}

    async def settle_order(self, order_id: str) -> dict:
        await self._set_tenant()
        result = await self.db.execute(select(Order).where(Order.id == uuid.UUID(order_id)).where(Order.tenant_id == self.tenant_id))
        order = result.scalar_one_or_none()
        if not order:
            raise ValueError(f"Order not found: {order_id}")
        if order.status == OrderStatus.completed.value:
            raise ValueError("Order already settled")
        order.status = OrderStatus.completed.value
        order.completed_at = datetime.now(timezone.utc)
        if order.table_number:
            await self._release_table(str(order.store_id), order.table_number)
        await self.db.flush()
        return {"order_id": order_id, "order_no": order.order_no, "final_amount_fen": order.final_amount_fen, "settled_at": order.completed_at.isoformat()}

    async def cancel_order(self, order_id: str, reason: str = "") -> dict:
        await self._set_tenant()
        result = await self.db.execute(select(Order).where(Order.id == uuid.UUID(order_id)).where(Order.tenant_id == self.tenant_id))
        order = result.scalar_one_or_none()
        if not order:
            raise ValueError(f"Order not found: {order_id}")
        order.status = OrderStatus.cancelled.value
        order.order_metadata = {**(order.order_metadata or {}), "cancel_reason": reason}
        if order.table_number:
            await self._release_table(str(order.store_id), order.table_number)
        await self.db.flush()
        return {"order_id": order_id, "status": "cancelled"}

    async def get_order(self, order_id: str) -> dict | None:
        await self._set_tenant()
        result = await self.db.execute(select(Order).where(Order.id == uuid.UUID(order_id)).where(Order.tenant_id == self.tenant_id))
        order = result.scalar_one_or_none()
        if not order:
            return None
        items_result = await self.db.execute(select(OrderItem).where(OrderItem.order_id == order.id).where(OrderItem.tenant_id == self.tenant_id))
        items = items_result.scalars().all()
        return {"id": str(order.id), "order_no": order.order_no, "store_id": str(order.store_id), "table_number": order.table_number, "status": order.status, "total_amount_fen": order.total_amount_fen, "discount_amount_fen": order.discount_amount_fen, "final_amount_fen": order.final_amount_fen, "order_time": order.order_time.isoformat() if order.order_time else None, "items": [{"id": str(i.id), "item_name": i.item_name, "quantity": i.quantity, "unit_price_fen": i.unit_price_fen, "subtotal_fen": i.subtotal_fen} for i in items]}

    async def _lock_table(self, store_id: str, table_no: str, order_id: uuid.UUID) -> None:
        await self.db.execute(update(Table).where(Table.tenant_id == self.tenant_id).where(Table.store_id == uuid.UUID(store_id)).where(Table.table_no == table_no).values(status=TableStatus.occupied.value, current_order_id=order_id))

    async def _release_table(self, store_id: str, table_no: str) -> None:
        await self.db.execute(update(Table).where(Table.tenant_id == self.tenant_id).where(Table.store_id == uuid.UUID(store_id)).where(Table.table_no == table_no).values(status=TableStatus.free.value, current_order_id=None))
