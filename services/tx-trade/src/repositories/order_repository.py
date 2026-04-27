"""订单 Repository — 封装 orders + order_items 的所有 DB 操作

架构约束：
  - 所有方法通过 AsyncSession 操作，由路由层 Depends(get_db) 注入
  - 每次 DB 操作前通过 set_config 设置 RLS tenant_id
  - 金额字段统一使用 int（分），严禁 float
  - 不直接 import 路由层任何模块（单向依赖）
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy import Date, and_, cast, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.ontology.src.entities import Order, OrderItem
from shared.ontology.src.enums import OrderStatus

logger = structlog.get_logger(__name__)

_SET_TENANT_SQL = text("SELECT set_config('app.tenant_id', :tid, true)")


class OrderRepository:
    """订单持久化操作 — Repository 模式

    所有公开方法首先设置 RLS tenant_id，保证数据隔离。
    """

    def __init__(self, session: AsyncSession, tenant_id: str) -> None:
        self.session = session
        self.tenant_id = UUID(tenant_id)
        self._tenant_id_str = tenant_id

    async def _set_rls(self) -> None:
        """设置 RLS 租户上下文 — 每次事务操作前必须调用"""
        await self.session.execute(_SET_TENANT_SQL, {"tid": self._tenant_id_str})

    # ─── 创建 ──────────────────────────────────────────────────────────────────

    async def create_order(
        self,
        store_id: str,
        order_no: str,
        order_type: str = "dine_in",
        table_no: Optional[str] = None,
        customer_id: Optional[str] = None,
        waiter_id: Optional[str] = None,
        guest_count: Optional[int] = None,
    ) -> dict:
        """创建订单（不含订单项）

        Returns:
            {"order_id": str, "order_no": str}
        """
        await self._set_rls()

        order = Order(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            order_no=order_no,
            store_id=UUID(store_id),
            table_number=table_no,
            customer_id=UUID(customer_id) if customer_id else None,
            waiter_id=waiter_id,
            order_type=order_type,
            guest_count=guest_count,
            total_amount_fen=0,
            discount_amount_fen=0,
            final_amount_fen=0,
            status=OrderStatus.pending.value,
        )
        self.session.add(order)
        await self.session.flush()

        logger.info(
            "order_created",
            order_id=str(order.id),
            order_no=order_no,
            store_id=store_id,
            table=table_no,
            tenant_id=self._tenant_id_str,
        )
        return {"order_id": str(order.id), "order_no": order_no}

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
        """向订单添加菜品并更新订单总额

        Returns:
            {"item_id": str, "subtotal_fen": int}
        """
        await self._set_rls()

        subtotal_fen = unit_price_fen * quantity
        item = OrderItem(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            order_id=UUID(order_id),
            dish_id=UUID(dish_id) if dish_id else None,
            item_name=dish_name,
            quantity=quantity,
            unit_price_fen=unit_price_fen,
            subtotal_fen=subtotal_fen,
            notes=notes,
            customizations=customizations or {},
        )
        self.session.add(item)

        # 更新订单总额
        await self.session.execute(
            update(Order)
            .where(Order.id == UUID(order_id), Order.tenant_id == self.tenant_id)
            .values(
                total_amount_fen=Order.total_amount_fen + subtotal_fen,
                final_amount_fen=Order.total_amount_fen + subtotal_fen - Order.discount_amount_fen,
                status=OrderStatus.confirmed.value,
            )
        )
        await self.session.flush()

        logger.info(
            "item_added",
            order_id=order_id,
            dish=dish_name,
            qty=quantity,
            tenant_id=self._tenant_id_str,
        )
        return {"item_id": str(item.id), "subtotal_fen": subtotal_fen}

    # ─── 查询 ──────────────────────────────────────────────────────────────────

    async def get_order(self, order_id: str) -> dict | None:
        """查询单笔订单 + 关联项

        Returns:
            订单详情 dict，未找到则返回 None
        """
        await self._set_rls()

        result = await self.session.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(
                Order.id == UUID(order_id),
                Order.tenant_id == self.tenant_id,
            )
        )
        order = result.scalar_one_or_none()
        if not order:
            return None

        return self._order_to_dict(order)

    async def list_orders(
        self,
        store_id: str,
        status: Optional[str] = None,
        date_str: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict], int]:
        """分页查询订单列表

        Returns:
            (items, total_count)
        """
        await self._set_rls()

        conditions = [
            Order.tenant_id == self.tenant_id,
            Order.store_id == UUID(store_id),
        ]
        if status:
            conditions.append(Order.status == status)
        if date_str:
            conditions.append(cast(Order.order_time, Date) == date_str)

        # 总数
        count_stmt = select(func.count(Order.id)).where(and_(*conditions))
        total = (await self.session.execute(count_stmt)).scalar() or 0

        # 分页数据
        offset = (page - 1) * size
        data_stmt = (
            select(Order)
            .options(selectinload(Order.items))
            .where(and_(*conditions))
            .order_by(Order.order_time.desc())
            .offset(offset)
            .limit(size)
        )
        result = await self.session.execute(data_stmt)
        orders = result.scalars().unique().all()

        items = [self._order_to_dict(o) for o in orders]
        logger.info(
            "orders_listed",
            store_id=store_id,
            status=status,
            page=page,
            total=total,
            tenant_id=self._tenant_id_str,
        )
        return items, total

    async def get_today_orders(self, store_id: str) -> list[dict]:
        """今日订单汇总"""
        await self._set_rls()

        today = date.today()
        stmt = (
            select(Order)
            .options(selectinload(Order.items))
            .where(
                Order.tenant_id == self.tenant_id,
                Order.store_id == UUID(store_id),
                cast(Order.order_time, Date) == today,
            )
            .order_by(Order.order_time.desc())
        )
        result = await self.session.execute(stmt)
        orders = result.scalars().unique().all()

        logger.info(
            "today_orders_fetched",
            store_id=store_id,
            count=len(orders),
            tenant_id=self._tenant_id_str,
        )
        return [self._order_to_dict(o) for o in orders]

    # ─── 更新 ──────────────────────────────────────────────────────────────────

    async def update_order_status(self, order_id: str, status: str) -> bool:
        """更新订单状态

        Returns:
            True 表示更新成功，False 表示订单不存在
        """
        await self._set_rls()

        result = await self.session.execute(
            update(Order)
            .where(
                Order.id == UUID(order_id),
                Order.tenant_id == self.tenant_id,
            )
            .values(status=status)
        )
        await self.session.flush()

        updated = result.rowcount > 0
        logger.info(
            "order_status_updated",
            order_id=order_id,
            status=status,
            success=updated,
            tenant_id=self._tenant_id_str,
        )
        return updated

    # ─── 内部工具 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _order_to_dict(order: Order) -> dict:
        """将 Order ORM 对象转为 dict"""
        return {
            "id": str(order.id),
            "order_no": order.order_no,
            "store_id": str(order.store_id),
            "table_number": order.table_number,
            "status": order.status,
            "order_type": order.order_type,
            "guest_count": order.guest_count,
            "total_amount_fen": order.total_amount_fen,
            "discount_amount_fen": order.discount_amount_fen,
            "final_amount_fen": order.final_amount_fen,
            "order_time": order.order_time.isoformat() if order.order_time else None,
            "completed_at": order.completed_at.isoformat() if order.completed_at else None,
            "items": [
                {
                    "id": str(i.id),
                    "dish_id": str(i.dish_id) if i.dish_id else None,
                    "item_name": i.item_name,
                    "quantity": i.quantity,
                    "unit_price_fen": i.unit_price_fen,
                    "subtotal_fen": i.subtotal_fen,
                    "notes": i.notes,
                    "customizations": i.customizations,
                }
                for i in (order.items or [])
            ],
        }
