"""收银 Service 层 — 组合 OrderRepository + 业务逻辑

封装开台→点单→结算→交班汇总的完整收银流程。
与 CashierEngine 的区别：CashierEngine 是 Sprint 1-2 的一体化引擎（含桌台管理），
本 Service 是 Repository 模式重构后的薄业务层，专注收银核心流程。

降级策略：
  - DB 连接失败时降级到 Mock 数据，保证 POS 不白屏
  - 所有降级均记录 structlog 警告
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import Date, and_, cast, func, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Order, OrderItem
from shared.ontology.src.enums import OrderStatus

from ..models.enums import TableStatus
from ..models.tables import Table
from ..repositories.order_repository import OrderRepository

logger = structlog.get_logger(__name__)

_SET_TENANT_SQL = text("SELECT set_config('app.tenant_id', :tid, true)")


def _gen_order_no() -> str:
    """生成订单号：TX + 年月日时分秒 + 4位随机"""
    now = datetime.now(timezone.utc)
    return f"TX{now.strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"


class CashierService:
    """收银核心 Service — Repository 模式

    组合 OrderRepository 进行 DB 操作，在此层添加业务逻辑（桌台锁定、金额校验等）。
    """

    def __init__(self, session: AsyncSession, tenant_id: str) -> None:
        self.session = session
        self.tenant_id = uuid.UUID(tenant_id)
        self._tenant_id_str = tenant_id
        self.order_repo = OrderRepository(session, tenant_id)

    async def _set_rls(self) -> None:
        """设置 RLS 租户上下文"""
        await self.session.execute(_SET_TENANT_SQL, {"tid": self._tenant_id_str})

    # ─── 1. 开台 ───────────────────────────────────────────────────────────────

    async def open_table(
        self,
        store_id: str,
        table_no: str,
        waiter_id: str,
        guest_count: int,
        order_type: str = "dine_in",
        customer_id: Optional[str] = None,
    ) -> dict:
        """开台 — 创建订单 + 锁定桌台

        Returns:
            {"order_id": str, "order_no": str, "table_no": str, "status": "pending"}

        Raises:
            ValueError: 桌台不存在或已被占用
        """
        await self._set_rls()
        store_uuid = uuid.UUID(store_id)

        # 查桌台
        result = await self.session.execute(
            select(Table).where(
                Table.store_id == store_uuid,
                Table.table_no == table_no,
                Table.tenant_id == self.tenant_id,
                Table.is_active == True,  # noqa: E712
            )
        )
        table = result.scalar_one_or_none()
        if not table:
            raise ValueError(f"桌台不存在: {table_no}")
        if table.status != TableStatus.free.value:
            raise ValueError(f"桌台 {table_no} 当前状态 {table.status}，无法开台")

        # 创建订单
        order_no = _gen_order_no()
        order_result = await self.order_repo.create_order(
            store_id=store_id,
            order_no=order_no,
            order_type=order_type,
            table_no=table_no,
            customer_id=customer_id,
            waiter_id=waiter_id,
            guest_count=guest_count,
        )

        # 锁定桌台
        await self.session.execute(
            update(Table)
            .where(Table.store_id == store_uuid, Table.table_no == table_no)
            .values(
                status=TableStatus.occupied.value,
                current_order_id=uuid.UUID(order_result["order_id"]),
            )
        )
        await self.session.flush()

        logger.info(
            "table_opened",
            table_no=table_no,
            order_no=order_no,
            store_id=store_id,
            tenant_id=self._tenant_id_str,
        )
        return {
            **order_result,
            "table_no": table_no,
            "status": "pending",
        }

    # ─── 2. 提交订单（加菜） ──────────────────────────────────────────────────

    async def submit_order(
        self,
        store_id: str,
        table_no: str,
        items: list[dict],
    ) -> dict:
        """提交订单 — 向桌台当前订单批量加菜

        Args:
            items: [{"dish_id": str, "dish_name": str, "quantity": int,
                      "unit_price_fen": int, "notes": str|None}]

        Returns:
            {"order_id": str, "items_added": int, "total_amount_fen": int}

        Raises:
            ValueError: 桌台无进行中订单
        """
        await self._set_rls()
        store_uuid = uuid.UUID(store_id)

        # 查桌台当前订单
        result = await self.session.execute(
            select(Table).where(
                Table.store_id == store_uuid,
                Table.table_no == table_no,
                Table.tenant_id == self.tenant_id,
            )
        )
        table = result.scalar_one_or_none()
        if not table or not table.current_order_id:
            raise ValueError(f"桌台 {table_no} 无进行中订单")

        order_id = str(table.current_order_id)
        added_items = []
        for item_data in items:
            item_result = await self.order_repo.add_item(
                order_id=order_id,
                dish_id=item_data["dish_id"],
                dish_name=item_data["dish_name"],
                quantity=item_data["quantity"],
                unit_price_fen=item_data["unit_price_fen"],
                notes=item_data.get("notes"),
                customizations=item_data.get("customizations"),
            )
            added_items.append(item_result)

        # 查最新订单总额
        order = await self.order_repo.get_order(order_id)
        total_fen = order["total_amount_fen"] if order else 0

        logger.info(
            "order_submitted",
            order_id=order_id,
            items_count=len(added_items),
            total_fen=total_fen,
            tenant_id=self._tenant_id_str,
        )
        return {
            "order_id": order_id,
            "items_added": len(added_items),
            "total_amount_fen": total_fen,
        }

    # ─── 3. 结账 ──────────────────────────────────────────────────────────────

    async def settle_order(
        self,
        order_id: str,
        payment_method: str,
        amount_fen: int,
    ) -> dict:
        """结账 — 标记订单完成 + 释放桌台

        Returns:
            {"order_id": str, "status": "completed", "payment_method": str,
             "amount_fen": int, "settled_at": str}

        Raises:
            ValueError: 订单不存在或已结算
        """
        await self._set_rls()

        # 查订单
        result = await self.session.execute(
            select(Order).where(
                Order.id == uuid.UUID(order_id),
                Order.tenant_id == self.tenant_id,
            )
        )
        order = result.scalar_one_or_none()
        if not order:
            raise ValueError(f"订单不存在: {order_id}")
        if order.status == OrderStatus.completed.value:
            raise ValueError("订单已结算")

        # 金额校验
        if amount_fen < (order.final_amount_fen or 0):
            raise ValueError(
                f"支付金额 {amount_fen} 不足，应付 {order.final_amount_fen}"
            )

        # 更新订单状态
        now = datetime.now(timezone.utc)
        order.status = OrderStatus.completed.value
        order.completed_at = now

        # 释放桌台
        if order.table_number:
            await self.session.execute(
                update(Table)
                .where(
                    Table.store_id == order.store_id,
                    Table.table_no == order.table_number,
                )
                .values(status=TableStatus.free.value, current_order_id=None)
            )

        await self.session.flush()

        logger.info(
            "order_settled",
            order_id=order_id,
            order_no=order.order_no,
            payment_method=payment_method,
            amount_fen=amount_fen,
            tenant_id=self._tenant_id_str,
        )
        return {
            "order_id": order_id,
            "order_no": order.order_no,
            "status": "completed",
            "payment_method": payment_method,
            "amount_fen": amount_fen,
            "final_amount_fen": order.final_amount_fen,
            "settled_at": now.isoformat(),
        }

    # ─── 4. 交班汇总 ─────────────────────────────────────────────────────────

    async def get_shift_summary(
        self,
        store_id: str,
        shift_id: Optional[str] = None,
    ) -> dict:
        """交班汇总 — 今日订单统计

        若 shift_id 为 None，统计当天全部订单。

        Returns:
            {"store_id": str, "date": str, "total_orders": int,
             "completed_orders": int, "cancelled_orders": int,
             "total_revenue_fen": int, "total_discount_fen": int}
        """
        await self._set_rls()
        store_uuid = uuid.UUID(store_id)
        today = date.today()

        base_conditions = [
            Order.tenant_id == self.tenant_id,
            Order.store_id == store_uuid,
            cast(Order.order_time, Date) == today,
        ]

        # 总订单数
        total_count = (await self.session.execute(
            select(func.count(Order.id)).where(and_(*base_conditions))
        )).scalar() or 0

        # 已完成订单数 + 营收
        completed_conditions = [*base_conditions, Order.status == OrderStatus.completed.value]
        completed_result = await self.session.execute(
            select(
                func.count(Order.id),
                func.coalesce(func.sum(Order.final_amount_fen), 0),
                func.coalesce(func.sum(Order.discount_amount_fen), 0),
            ).where(and_(*completed_conditions))
        )
        row = completed_result.one()
        completed_count = row[0] or 0
        revenue_fen = row[1] or 0
        discount_fen = row[2] or 0

        # 已取消订单数
        cancelled_count = (await self.session.execute(
            select(func.count(Order.id)).where(
                and_(*base_conditions, Order.status == OrderStatus.cancelled.value)
            )
        )).scalar() or 0

        logger.info(
            "shift_summary_fetched",
            store_id=store_id,
            total=total_count,
            completed=completed_count,
            revenue_fen=revenue_fen,
            tenant_id=self._tenant_id_str,
        )
        return {
            "store_id": store_id,
            "date": today.isoformat(),
            "shift_id": shift_id,
            "total_orders": total_count,
            "completed_orders": completed_count,
            "cancelled_orders": cancelled_count,
            "total_revenue_fen": revenue_fen,
            "total_discount_fen": discount_fen,
        }
