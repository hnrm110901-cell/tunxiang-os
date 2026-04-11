"""收银核心引擎 — Sprint 1-2 交付级

完整实现10个API端点的后端逻辑，覆盖开台→点单→结算全流程。
所有金额单位：分（fen）。三条硬约束在此层校验。
"""
import asyncio
import math
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import Date, and_, cast, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import DiscountEventType, OrderEventType, PaymentEventType
from shared.ontology.src.entities import Customer, Dish, Order, OrderItem, Store
from shared.ontology.src.enums import OrderStatus

from ..models.enums import TableStatus
from ..models.tables import Table
from .state_machine import (
    TABLE_STATES,
    can_table_transition,
)

logger = structlog.get_logger()

AGENT_SERVICE_URL = os.getenv("AGENT_SERVICE_URL", "http://tx-agent:8008")


def _gen_order_no() -> str:
    """生成订单号：TX + 年月日时分秒 + 4位随机"""
    now = datetime.now(timezone.utc)
    return f"TX{now.strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"


# ─── 桌台状态到模型枚举的映射 ───
_STATE_MACHINE_TO_TABLE_STATUS = {
    "empty": TableStatus.free.value,
    "reserved": TableStatus.reserved.value,
    "dining": TableStatus.occupied.value,
    "pending_checkout": TableStatus.occupied.value,
    "pending_cleanup": TableStatus.cleaning.value,
    "locked": TableStatus.occupied.value,
    "maintenance": TableStatus.occupied.value,
}

# 反向映射：model enum → state machine
_TABLE_STATUS_TO_STATE_MACHINE = {
    TableStatus.free.value: "empty",
    TableStatus.reserved.value: "reserved",
    TableStatus.occupied.value: "dining",
    TableStatus.cleaning.value: "pending_cleanup",
}


async def _trigger_marketing_attribution(
    *,
    tenant_id: str,
    member_id: str,
    order_id: str,
    order_amount_fen: int,
    store_id: str,
) -> None:
    """火花旁路：将订单归因到最近的营销触达记录（不阻塞收银流程）"""
    import httpx as _httpx
    try:
        async with _httpx.AsyncClient(timeout=8.0) as client:
            await client.post(
                f"{AGENT_SERVICE_URL}/api/v1/agent/ai-marketing/attribute-order",
                headers={"X-Tenant-ID": tenant_id},
                json={
                    "member_id": member_id,
                    "order_id": order_id,
                    "order_amount_fen": order_amount_fen,
                    "store_id": store_id,
                    "attribution_window_hours": 72,
                },
            )
    except (_httpx.ConnectError, _httpx.TimeoutException) as exc:
        import structlog as _structlog
        _structlog.get_logger().debug(
            "marketing_attribution_skipped",
            order_id=order_id,
            error=str(exc),
        )


class CashierEngine:
    """收银核心引擎 — Sprint 1-2 交付级

    完整实现10个API端点的后端逻辑，覆盖开台→点单→结算全流程。
    """

    # 默认毛利底线30%
    DEFAULT_MARGIN_FLOOR = 0.30
    # 默认茶位费（分）
    DEFAULT_TEA_CHARGE_FEN = 800  # ¥8 per person

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = uuid.UUID(tenant_id)

    # ─────────────────────────────────────
    # 1. Table Management
    # ─────────────────────────────────────

    async def open_table(
        self,
        store_id: str,
        table_no: str,
        waiter_id: str,
        guest_count: int,
        order_type: str = "dine_in",
        customer_id: Optional[str] = None,
    ) -> dict:
        """开台 — 创建订单 + 锁定桌台 + 自动加茶位费"""
        store_uuid = uuid.UUID(store_id)

        # 查桌台
        result = await self.db.execute(
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
        order = Order(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            order_no=order_no,
            store_id=store_uuid,
            table_number=table_no,
            customer_id=uuid.UUID(customer_id) if customer_id else None,
            waiter_id=waiter_id,
            sales_channel=order_type,
            guest_count=guest_count,
            total_amount_fen=0,
            discount_amount_fen=0,
            final_amount_fen=0,
            status=OrderStatus.pending.value,
        )
        self.db.add(order)

        # 锁定桌台
        table.status = TableStatus.occupied.value
        table.current_order_id = order.id

        await self.db.flush()

        # 自动加茶位费（如果门店配置了）
        store_result = await self.db.execute(
            select(Store).where(Store.id == store_uuid)
        )
        store = store_result.scalar_one_or_none()
        tea_charge_fen = 0
        if store and store.config and store.config.get("tea_charge_per_person_fen"):
            tea_charge_per = store.config["tea_charge_per_person_fen"]
            tea_charge_fen = tea_charge_per * guest_count
            await self._add_auto_charge(order.id, "茶位费", tea_charge_fen, guest_count)

        logger.info(
            "table_opened",
            order_no=order_no,
            store_id=store_id,
            table=table_no,
            guest_count=guest_count,
            tea_charge_fen=tea_charge_fen,
        )

        return {
            "order_id": str(order.id),
            "order_no": order_no,
            "table_no": table_no,
            "status": order.status,
            "guest_count": guest_count,
            "tea_charge_fen": tea_charge_fen,
        }

    async def get_table_map(self, store_id: str) -> list[dict]:
        """获取桌台地图 — 所有桌台及当前状态、订单信息、用餐时长"""
        store_uuid = uuid.UUID(store_id)
        result = await self.db.execute(
            select(Table).where(
                Table.store_id == store_uuid,
                Table.tenant_id == self.tenant_id,
                Table.is_active == True,  # noqa: E712
            ).order_by(Table.sort_order, Table.table_no)
        )
        tables = result.scalars().all()

        table_map = []
        now = datetime.now(timezone.utc)

        for t in tables:
            entry = {
                "table_no": t.table_no,
                "area": t.area,
                "floor": t.floor,
                "seats": t.seats,
                "status": t.status,
                "current_order_id": str(t.current_order_id) if t.current_order_id else None,
                "order_info": None,
                "duration_min": None,
            }

            if t.current_order_id:
                order_result = await self.db.execute(
                    select(Order).where(Order.id == t.current_order_id)
                )
                order = order_result.scalar_one_or_none()
                if order:
                    duration = (now - order.order_time).total_seconds() / 60 if order.order_time else 0
                    entry["order_info"] = {
                        "order_no": order.order_no,
                        "guest_count": order.guest_count,
                        "total_amount_fen": order.total_amount_fen,
                        "final_amount_fen": order.final_amount_fen,
                        "status": order.status,
                        "waiter_id": order.waiter_id,
                    }
                    entry["duration_min"] = round(duration, 1)

            table_map.append(entry)

        return table_map

    async def change_table_status(
        self,
        store_id: str,
        table_no: str,
        target_status: str,
        reason: Optional[str] = None,
    ) -> dict:
        """变更桌台状态 — 通过 state_machine 校验合法性"""
        store_uuid = uuid.UUID(store_id)
        result = await self.db.execute(
            select(Table).where(
                Table.store_id == store_uuid,
                Table.table_no == table_no,
                Table.tenant_id == self.tenant_id,
            )
        )
        table = result.scalar_one_or_none()
        if not table:
            raise ValueError(f"桌台不存在: {table_no}")

        # 映射当前状态到 state machine 语义
        current_sm = _TABLE_STATUS_TO_STATE_MACHINE.get(table.status, table.status)
        target_sm = target_status

        # 检查状态转换合法性
        if not can_table_transition(current_sm, target_sm):
            raise ValueError(
                f"非法状态转换: {current_sm}({TABLE_STATES.get(current_sm)}) → "
                f"{target_sm}({TABLE_STATES.get(target_sm)})"
            )

        # 映射 target 到 model enum
        new_model_status = _STATE_MACHINE_TO_TABLE_STATUS.get(target_sm, target_sm)
        old_status = table.status
        table.status = new_model_status

        # 如果切到 empty/free，清除关联订单
        if target_sm == "empty":
            table.current_order_id = None

        await self.db.flush()
        logger.info(
            "table_status_changed",
            table_no=table_no,
            from_status=old_status,
            to_status=new_model_status,
            reason=reason,
        )

        return {
            "table_no": table_no,
            "old_status": old_status,
            "new_status": new_model_status,
            "reason": reason,
        }

    # ─────────────────────────────────────
    # 2. Order Items
    # ─────────────────────────────────────

    async def add_item(
        self,
        order_id: str,
        dish_id: str,
        dish_name: str,
        qty: int,
        unit_price_fen: int,
        notes: Optional[str] = None,
        customizations: Optional[dict] = None,
        pricing_mode: str = "fixed",
        weight_value: Optional[float] = None,
    ) -> dict:
        """加菜 — 支持固定价/称重/时价三种定价模式"""
        order_uuid = uuid.UUID(order_id)
        dish_uuid = uuid.UUID(dish_id) if dish_id else None

        # 单次查询同时获取 Order + Dish（合并 2 次 DB 往返为 1 次）
        if dish_uuid:
            result = await self.db.execute(
                select(Order, Dish)
                .outerjoin(Dish, Dish.id == dish_uuid)
                .where(Order.id == order_uuid, Order.tenant_id == self.tenant_id)
            )
            row = result.one_or_none()
            if not row:
                raise ValueError(f"订单不存在: {order_id}")
            order, dish = row[0], row[1]
        else:
            order = await self._get_order(order_uuid)
            dish = None

        if order.status in (OrderStatus.completed.value, OrderStatus.cancelled.value):
            raise ValueError(f"订单状态 {order.status}，无法加菜")

        # 计算小计
        if pricing_mode == "weighted" and weight_value is not None:
            subtotal_fen = round(unit_price_fen * weight_value)
        else:
            subtotal_fen = unit_price_fen * qty

        # BOM 成本（从已加载的 dish 对象取，无额外查询）
        food_cost_fen = None
        gross_margin = None
        if dish and dish.cost_fen:
            food_cost_fen = dish.cost_fen * qty
            if subtotal_fen > 0:
                gross_margin = round((subtotal_fen - food_cost_fen) / subtotal_fen, 4)

        item = OrderItem(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            order_id=order_uuid,
            dish_id=dish_uuid,
            item_name=dish_name,
            quantity=qty,
            unit_price_fen=unit_price_fen,
            subtotal_fen=subtotal_fen,
            food_cost_fen=food_cost_fen,
            gross_margin=gross_margin,
            notes=notes,
            customizations=customizations or {},
            pricing_mode=pricing_mode,
            weight_value=weight_value,
        )
        self.db.add(item)

        # 重新计算订单总额（与 INSERT 合并为单次 flush）
        new_total = order.total_amount_fen + subtotal_fen
        new_final = new_total - order.discount_amount_fen
        order.total_amount_fen = new_total
        order.final_amount_fen = new_final
        order.status = OrderStatus.confirmed.value

        await self.db.flush()
        logger.info(
            "item_added",
            order_id=order_id,
            dish=dish_name,
            qty=qty,
            pricing_mode=pricing_mode,
            subtotal_fen=subtotal_fen,
        )

        return {
            "item_id": str(item.id),
            "subtotal_fen": subtotal_fen,
            "order_total_fen": new_total,
            "order_final_fen": new_final,
        }

    async def update_item(
        self,
        order_id: str,
        item_id: str,
        quantity: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> dict:
        """改菜 — 修改数量或备注"""
        item_uuid = uuid.UUID(item_id)
        result = await self.db.execute(
            select(OrderItem).where(
                OrderItem.id == item_uuid,
                OrderItem.order_id == uuid.UUID(order_id),
            )
        )
        item = result.scalar_one_or_none()
        if not item:
            raise ValueError(f"菜品明细不存在: {item_id}")

        old_subtotal = item.subtotal_fen
        diff = 0

        if quantity is not None and quantity != item.quantity:
            if item.pricing_mode == "weighted" and item.weight_value:
                new_subtotal = round(item.unit_price_fen * item.weight_value)
            else:
                new_subtotal = item.unit_price_fen * quantity
            diff = new_subtotal - old_subtotal
            item.quantity = quantity
            item.subtotal_fen = new_subtotal

            # 更新订单总额
            order = await self._get_order(item.order_id)
            new_total = order.total_amount_fen + diff
            new_final = new_total - order.discount_amount_fen
            await self.db.execute(
                update(Order)
                .where(Order.id == item.order_id)
                .values(total_amount_fen=new_total, final_amount_fen=new_final)
            )

        if notes is not None:
            item.notes = notes

        await self.db.flush()

        # 重新读取订单
        order = await self._get_order(uuid.UUID(order_id))
        return {
            "item_id": item_id,
            "new_quantity": item.quantity,
            "new_subtotal_fen": item.subtotal_fen,
            "diff_fen": diff,
            "order_total_fen": order.total_amount_fen,
            "order_final_fen": order.final_amount_fen,
        }

    async def remove_item(
        self,
        order_id: str,
        item_id: str,
        reason: str = "",
    ) -> dict:
        """删菜 — 记录原因并自动重算总额"""
        item_uuid = uuid.UUID(item_id)
        order_uuid = uuid.UUID(order_id)

        result = await self.db.execute(
            select(OrderItem).where(
                OrderItem.id == item_uuid,
                OrderItem.order_id == order_uuid,
            )
        )
        item = result.scalar_one_or_none()
        if not item:
            raise ValueError(f"菜品明细不存在: {item_id}")

        deducted = item.subtotal_fen

        # 标记退菜（软删除记录原因）
        item.return_flag = True
        item.return_reason = reason

        # 更新订单总额
        order = await self._get_order(order_uuid)
        new_total = order.total_amount_fen - deducted
        new_final = new_total - order.discount_amount_fen

        await self.db.execute(
            update(Order)
            .where(Order.id == order_uuid)
            .values(total_amount_fen=new_total, final_amount_fen=new_final)
        )

        # 真删除明细
        await self.db.delete(item)
        await self.db.flush()

        logger.info("item_removed", order_id=order_id, item_id=item_id, reason=reason)

        return {
            "removed_item_id": item_id,
            "deducted_fen": deducted,
            "reason": reason,
            "order_total_fen": new_total,
            "order_final_fen": new_final,
        }

    # ─────────────────────────────────────
    # 3. Discounts
    # ─────────────────────────────────────

    async def apply_discount(
        self,
        order_id: str,
        discount_type: str,
        discount_value: float,
        reason: str = "",
        approval_id: Optional[str] = None,
    ) -> dict:
        """应用折扣 — 支持百分比/固定金额/免单/会员价

        硬约束#1: 毛利底线校验。折扣后毛利率低于阈值则拒绝。

        Args:
            discount_type: percent_off / amount_off / free_item / member_price
            discount_value: percent_off时为折扣率(如0.8=打八折)；amount_off时为减免金额(分)
        """
        order_uuid = uuid.UUID(order_id)
        order = await self._get_order(order_uuid)

        if order.status in (OrderStatus.completed.value, OrderStatus.cancelled.value):
            raise ValueError(f"订单状态 {order.status}，无法应用折扣")

        total = order.total_amount_fen

        # 计算折扣金额
        if discount_type == "percent_off":
            # discount_value = 0.8 means 打八折, 折扣额 = total * (1 - 0.8)
            discount_fen = round(total * (1.0 - discount_value))
        elif discount_type == "amount_off" or discount_type == "free_item":
            discount_fen = int(discount_value)
        elif discount_type == "member_price":
            # discount_value 是会员价总额（分），折扣 = 原价 - 会员价
            discount_fen = total - int(discount_value)
        else:
            raise ValueError(f"不支持的折扣类型: {discount_type}")

        if discount_fen < 0:
            discount_fen = 0

        new_final = total - discount_fen
        if new_final < 0:
            raise ValueError("折扣金额超过订单总额")

        # ─── 硬约束#1: 毛利底线校验 ───
        total_cost_fen = await self._calc_order_cost(order_uuid)
        margin_check = {"passed": True, "margin": None, "floor": self.DEFAULT_MARGIN_FLOOR}

        if total_cost_fen is not None and new_final > 0:
            margin = (new_final - total_cost_fen) / new_final
            margin_check["margin"] = round(margin, 4)

            # 查门店自定义毛利底线
            store_result = await self.db.execute(
                select(Store).where(Store.id == order.store_id)
            )
            store = store_result.scalar_one_or_none()
            floor = self.DEFAULT_MARGIN_FLOOR
            if store and store.cost_ratio_target:
                floor = 1.0 - store.cost_ratio_target
            margin_check["floor"] = floor

            if margin < floor and not approval_id:
                margin_check["passed"] = False
                logger.warning(
                    "margin_floor_needs_approval",
                    order_id=order_id,
                    margin=margin,
                    floor=floor,
                    discount_fen=discount_fen,
                )

                # 创建审批单而非直接拒绝
                try:
                    from .approval_service import ApprovalService
                    approval_svc = ApprovalService(
                        self.db, str(self.tenant_id), str(order.store_id)
                    )
                    approval_result = await approval_svc.create_approval(
                        order_id=order_id,
                        discount_info={
                            "discount_type": discount_type,
                            "discount_value": discount_value,
                            "discount_fen": discount_fen,
                            "current_margin": round(margin, 4),
                            "margin_floor": floor,
                            "new_final_fen": new_final,
                        },
                        reason=reason or f"折扣后毛利率 {margin:.1%} 低于底线 {floor:.1%}",
                    )
                    return {
                        "applied": False,
                        "needs_approval": True,
                        "approval_id": approval_result["approval_id"],
                        "discount_fen": 0,
                        "new_total_fen": order.final_amount_fen,
                        "margin_check": margin_check,
                        "message": f"折扣后毛利率 {margin:.1%} 低于底线 {floor:.1%}，已创建审批单",
                    }
                except (ValueError, ImportError) as exc:
                    logger.error(
                        "approval_creation_failed",
                        order_id=order_id,
                        error=str(exc),
                    )
                    return {
                        "applied": False,
                        "needs_approval": True,
                        "approval_id": None,
                        "discount_fen": 0,
                        "new_total_fen": order.final_amount_fen,
                        "margin_check": margin_check,
                        "error": f"折扣后毛利率 {margin:.1%} 低于底线 {floor:.1%}，审批单创建失败",
                    }

        # 应用折扣
        order.discount_amount_fen = discount_fen
        order.final_amount_fen = new_final
        order.discount_type = discount_type
        order.gross_margin_before = (
            round((total - total_cost_fen) / total, 4) if total_cost_fen and total > 0 else None
        )
        order.gross_margin_after = margin_check.get("margin")
        order.margin_alert_flag = not margin_check["passed"]
        order.order_metadata = {
            **(order.order_metadata or {}),
            "discount_reason": reason,
            "discount_approval_id": approval_id,
        }

        await self.db.flush()
        logger.info(
            "discount_applied",
            order_id=order_id,
            discount_type=discount_type,
            discount_fen=discount_fen,
            new_final=new_final,
        )

        # ─── Phase 1 平行事件写入：折扣应用事件 ───
        asyncio.create_task(emit_event(
            event_type=DiscountEventType.APPLIED,
            tenant_id=self.tenant_id,
            stream_id=order_id,
            payload={
                "discount_type": discount_type,
                "discount_fen": discount_fen,
                "original_total_fen": total,
                "new_total_fen": new_final,
                "reason": reason,
                "approval_id": approval_id,
                "margin_after": margin_check.get("margin"),
                "margin_passed": margin_check["passed"],
                "threshold_exceeded": not margin_check["passed"],
            },
            store_id=str(order.store_id) if order.store_id else None,
            source_service="tx-trade",
            metadata={"order_no": order.order_no},
        ))

        return {
            "applied": True,
            "discount_fen": discount_fen,
            "new_total_fen": new_final,
            "margin_check": margin_check,
        }

    # ─────────────────────────────────────
    # 4. Settlement
    # ─────────────────────────────────────

    async def settle_order(
        self,
        order_id: str,
        payments: list[dict],
        auto_pay: bool = False,
        customer_id: Optional[str] = None,
    ) -> dict:
        """结算 — 多支付方式结账 / 无感支付

        Args:
            payments: [{method, amount_fen, trade_no?}]
            auto_pay: 如果为 True 且顾客有储值卡余额 >= final_amount，自动扣款
            customer_id: 顾客ID（auto_pay 时必传）
        """
        order_uuid = uuid.UUID(order_id)
        order = await self._get_order(order_uuid)

        if order.status == OrderStatus.completed.value:
            raise ValueError("订单已结算")
        if order.status == OrderStatus.cancelled.value:
            raise ValueError("订单已取消")

        # ─── 无感支付：储值卡自动扣款 ───
        auto_pay_result: Optional[dict] = None
        if auto_pay and customer_id:
            auto_pay_result = await self._try_auto_pay(
                order_id=order_id,
                customer_id=customer_id,
                final_amount_fen=order.final_amount_fen,
            )
            if auto_pay_result and auto_pay_result.get("success"):
                # 自动扣款成功，构造支付记录
                payments = [{
                    "method": "member_balance",
                    "amount_fen": order.final_amount_fen,
                }]

        # 验证支付总额 >= 应付金额
        total_paid = sum(p["amount_fen"] for p in payments)
        if total_paid < order.final_amount_fen:
            raise ValueError(
                f"支付金额 {total_paid} 不足，应付 {order.final_amount_fen}"
            )

        # 计算找零（仅现金）
        change_fen = 0
        if total_paid > order.final_amount_fen:
            cash_payments = [p for p in payments if p["method"] == "cash"]
            if cash_payments:
                change_fen = total_paid - order.final_amount_fen

        # 创建支付记录
        from ..models.enums import PaymentStatus
        from ..models.payment import Payment

        payment_records = []
        for p in payments:
            pay_no = f"PAY{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"
            payment = Payment(
                id=uuid.uuid4(),
                tenant_id=self.tenant_id,
                order_id=order_uuid,
                payment_no=pay_no,
                method=p["method"],
                amount_fen=p["amount_fen"],
                status=PaymentStatus.paid.value,
                trade_no=p.get("trade_no"),
                paid_at=datetime.now(timezone.utc),
                payment_category=self._method_to_category(p["method"]),
            )
            self.db.add(payment)
            payment_records.append({
                "payment_id": str(payment.id),
                "payment_no": pay_no,
                "method": p["method"],
                "amount_fen": p["amount_fen"],
                "trade_no": p.get("trade_no"),
            })

        # 更新订单状态
        order.status = OrderStatus.completed.value
        order.completed_at = datetime.now(timezone.utc)

        # 释放桌台
        if order.table_number:
            await self._release_table(str(order.store_id), order.table_number)

        await self.db.flush()

        # 构造小票数据
        receipt_data = {
            "order_no": order.order_no,
            "table_number": order.table_number,
            "total_amount_fen": order.total_amount_fen,
            "discount_amount_fen": order.discount_amount_fen,
            "final_amount_fen": order.final_amount_fen,
            "payments": payment_records,
            "change_fen": change_fen,
            "settled_at": order.completed_at.isoformat(),
        }

        logger.info(
            "order_settled",
            order_no=order.order_no,
            final_fen=order.final_amount_fen,
            payments_count=len(payments),
            auto_pay=auto_pay,
        )

        # ─── Phase 1 平行事件写入：订单完成 + 支付确认 ───
        payment_methods = [p["method"] for p in payments]
        asyncio.create_task(emit_event(
            event_type=OrderEventType.PAID,
            tenant_id=self.tenant_id,
            stream_id=order_id,
            payload={
                "order_no": order.order_no,
                "final_amount_fen": order.final_amount_fen,
                "discount_amount_fen": order.discount_amount_fen,
                "total_amount_fen": order.total_amount_fen,
                "payment_methods": payment_methods,
                "customer_id": str(order.customer_id) if order.customer_id else None,
                "table_number": order.table_number,
                "change_fen": change_fen,
            },
            store_id=str(order.store_id) if order.store_id else None,
            source_service="tx-trade",
            metadata={"auto_pay": auto_pay},
        ))
        asyncio.create_task(emit_event(
            event_type=PaymentEventType.CONFIRMED,
            tenant_id=self.tenant_id,
            stream_id=order_id,
            payload={
                "order_no": order.order_no,
                "amount_fen": order.final_amount_fen,
                "payment_records": payment_records,
                "channel": payment_methods[0] if payment_methods else "unknown",
            },
            store_id=str(order.store_id) if order.store_id else None,
            source_service="tx-trade",
        ))

        # ─── 营销归因（火花旁路，不阻塞结算）───
        effective_customer_id = customer_id or (
            str(order.customer_id) if order.customer_id else None
        )
        if effective_customer_id:
            asyncio.create_task(_trigger_marketing_attribution(
                tenant_id=str(self.tenant_id),
                member_id=effective_customer_id,
                order_id=order_id,
                order_amount_fen=order.final_amount_fen,
                store_id=str(order.store_id) if order.store_id else "",
            ))

        # ─── 支付后推券（异步不阻塞） ───
        if effective_customer_id:
            try:
                from .post_payment_service import PostPaymentService

                post_svc = PostPaymentService(self.db, str(self.tenant_id))
                await post_svc.trigger_post_payment(order_id, effective_customer_id)
            except (ImportError, ValueError, RuntimeError) as exc:
                logger.warning(
                    "post_payment_trigger_failed",
                    order_id=order_id,
                    error=str(exc),
                )

        result = {
            "settled": True,
            "payment_records": payment_records,
            "change_fen": change_fen,
            "receipt_data": receipt_data,
        }

        if auto_pay_result and auto_pay_result.get("success"):
            result["auto_pay"] = {
                "deducted_fen": auto_pay_result["deducted_fen"],
                "balance_fen": auto_pay_result["balance_fen"],
                "card_id": auto_pay_result["card_id"],
            }

        return result

    async def cancel_order(
        self,
        order_id: str,
        reason: str = "",
    ) -> dict:
        """取消订单 — 释放桌台"""
        order_uuid = uuid.UUID(order_id)
        order = await self._get_order(order_uuid)

        if order.status == OrderStatus.completed.value:
            raise ValueError("已结算订单无法取消，请走退款流程")
        if order.status == OrderStatus.cancelled.value:
            raise ValueError("订单已取消")

        order.status = OrderStatus.cancelled.value
        order.order_metadata = {
            **(order.order_metadata or {}),
            "cancel_reason": reason,
            "cancelled_at": datetime.now(timezone.utc).isoformat(),
        }

        # 释放桌台
        if order.table_number:
            await self._release_table(str(order.store_id), order.table_number)

        await self.db.flush()
        logger.info("order_cancelled", order_no=order.order_no, reason=reason)
        return {
            "order_id": order_id,
            "order_no": order.order_no,
            "status": "cancelled",
            "reason": reason,
        }

    # ─────────────────────────────────────
    # 5. Query
    # ─────────────────────────────────────

    async def get_order_detail(self, order_id: str) -> dict:
        """查询订单完整详情（含明细、支付、折扣、桌台信息）"""
        order_uuid = uuid.UUID(order_id)
        order = await self._get_order(order_uuid)

        # 查明细
        items_result = await self.db.execute(
            select(OrderItem).where(OrderItem.order_id == order_uuid)
        )
        items = items_result.scalars().all()

        # 查支付记录
        from ..models.payment import Payment
        payments_result = await self.db.execute(
            select(Payment).where(Payment.order_id == order_uuid)
        )
        payments = payments_result.scalars().all()

        # 查桌台
        table_info = None
        if order.table_number:
            table_result = await self.db.execute(
                select(Table).where(
                    Table.store_id == order.store_id,
                    Table.table_no == order.table_number,
                )
            )
            table = table_result.scalar_one_or_none()
            if table:
                table_info = {
                    "table_no": table.table_no,
                    "area": table.area,
                    "floor": table.floor,
                    "seats": table.seats,
                    "status": table.status,
                }

        return {
            "id": str(order.id),
            "order_no": order.order_no,
            "store_id": str(order.store_id),
            "table_number": order.table_number,
            "table_info": table_info,
            "customer_id": str(order.customer_id) if order.customer_id else None,
            "waiter_id": order.waiter_id,
            "guest_count": order.guest_count,
            "status": order.status,
            "sales_channel": order.sales_channel,
            "total_amount_fen": order.total_amount_fen,
            "discount_amount_fen": order.discount_amount_fen,
            "discount_type": order.discount_type,
            "final_amount_fen": order.final_amount_fen,
            "margin_alert_flag": order.margin_alert_flag,
            "order_time": order.order_time.isoformat() if order.order_time else None,
            "completed_at": order.completed_at.isoformat() if order.completed_at else None,
            "notes": order.notes,
            "items": [
                {
                    "id": str(i.id),
                    "dish_id": str(i.dish_id) if i.dish_id else None,
                    "item_name": i.item_name,
                    "quantity": i.quantity,
                    "unit_price_fen": i.unit_price_fen,
                    "subtotal_fen": i.subtotal_fen,
                    "pricing_mode": i.pricing_mode,
                    "weight_value": float(i.weight_value) if i.weight_value else None,
                    "food_cost_fen": i.food_cost_fen,
                    "gross_margin": float(i.gross_margin) if i.gross_margin else None,
                    "notes": i.notes,
                    "customizations": i.customizations,
                }
                for i in items
            ],
            "payments": [
                {
                    "payment_id": str(p.id),
                    "payment_no": p.payment_no,
                    "method": p.method,
                    "amount_fen": p.amount_fen,
                    "status": p.status,
                    "trade_no": p.trade_no,
                    "paid_at": p.paid_at.isoformat() if p.paid_at else None,
                }
                for p in payments
            ],
            "metadata": order.order_metadata,
        }

    async def list_orders(
        self,
        store_id: str,
        status: Optional[str] = None,
        date_str: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页查询订单列表"""
        store_uuid = uuid.UUID(store_id)
        conditions = [
            Order.store_id == store_uuid,
            Order.tenant_id == self.tenant_id,
        ]

        if status:
            conditions.append(Order.status == status)

        if date_str:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            conditions.append(
                cast(Order.order_time, Date) == target_date
            )

        # 总数
        count_q = select(func.count()).select_from(Order).where(and_(*conditions))
        total_result = await self.db.execute(count_q)
        total = total_result.scalar()

        # 分页查询
        offset = (page - 1) * size
        query = (
            select(Order)
            .where(and_(*conditions))
            .order_by(Order.order_time.desc())
            .offset(offset)
            .limit(size)
        )
        result = await self.db.execute(query)
        orders = result.scalars().all()

        items = [
            {
                "id": str(o.id),
                "order_no": o.order_no,
                "table_number": o.table_number,
                "status": o.status,
                "total_amount_fen": o.total_amount_fen,
                "discount_amount_fen": o.discount_amount_fen,
                "final_amount_fen": o.final_amount_fen,
                "guest_count": o.guest_count,
                "waiter_id": o.waiter_id,
                "order_time": o.order_time.isoformat() if o.order_time else None,
                "completed_at": o.completed_at.isoformat() if o.completed_at else None,
            }
            for o in orders
        ]

        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
            "pages": math.ceil(total / size) if total else 0,
        }

    # ─────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────

    async def _get_order(self, order_id: uuid.UUID) -> Order:
        result = await self.db.execute(
            select(Order).where(Order.id == order_id, Order.tenant_id == self.tenant_id)
        )
        order = result.scalar_one_or_none()
        if not order:
            raise ValueError(f"订单不存在: {order_id}")
        return order

    async def _add_auto_charge(
        self,
        order_id: uuid.UUID,
        name: str,
        total_fen: int,
        qty: int,
    ) -> None:
        """自动添加费用项（如茶位费）"""
        unit_price = total_fen // qty if qty > 0 else total_fen
        item = OrderItem(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            order_id=order_id,
            dish_id=None,
            item_name=name,
            quantity=qty,
            unit_price_fen=unit_price,
            subtotal_fen=total_fen,
            notes="系统自动添加",
            customizations={},
            pricing_mode="fixed",
        )
        self.db.add(item)

        await self.db.execute(
            update(Order)
            .where(Order.id == order_id)
            .values(
                total_amount_fen=Order.total_amount_fen + total_fen,
                final_amount_fen=Order.total_amount_fen + total_fen - Order.discount_amount_fen,
            )
        )

    async def _calc_order_cost(self, order_id: uuid.UUID) -> Optional[int]:
        """计算订单BOM总成本，用于毛利校验"""
        result = await self.db.execute(
            select(OrderItem).where(OrderItem.order_id == order_id)
        )
        items = result.scalars().all()

        total_cost = 0
        has_cost = False
        for item in items:
            if item.food_cost_fen is not None:
                total_cost += item.food_cost_fen
                has_cost = True

        return total_cost if has_cost else None

    async def _release_table(self, store_id: str, table_no: str) -> None:
        await self.db.execute(
            update(Table)
            .where(
                Table.store_id == uuid.UUID(store_id),
                Table.table_no == table_no,
            )
            .values(status=TableStatus.free.value, current_order_id=None)
        )

    async def _try_auto_pay(
        self,
        order_id: str,
        customer_id: str,
        final_amount_fen: int,
    ) -> Optional[dict]:
        """无感支付 — 尝试从储值卡自动扣款

        查找顾客活跃储值卡，余额 >= final_amount 时自动扣款。
        扣款成功后推送微信通知。
        """
        from .coupon_service import _StoredValueStore

        # 遍历储值卡找到该顾客的卡（余额充足）
        target_card: Optional[dict] = None
        for card_data in _StoredValueStore._cards.values():
            if (
                card_data.get("customer_id") == customer_id
                and card_data.get("tenant_id") == str(self.tenant_id)
                and card_data.get("status") == "active"
                and card_data.get("balance_fen", 0) >= final_amount_fen
            ):
                target_card = card_data
                break

        if not target_card:
            logger.info(
                "auto_pay_no_eligible_card",
                order_id=order_id,
                customer_id=customer_id,
                required_fen=final_amount_fen,
            )
            return {"success": False, "reason": "无可用储值卡或余额不足"}

        # 执行扣款
        from .coupon_service import deduct_stored_value

        deduct_result = await deduct_stored_value(
            card_id=target_card["card_id"],
            amount_fen=final_amount_fen,
            order_id=order_id,
            tenant_id=str(self.tenant_id),
            db=self.db,
        )

        logger.info(
            "auto_pay_success",
            order_id=order_id,
            customer_id=customer_id,
            card_id=target_card["card_id"],
            deducted_fen=final_amount_fen,
            balance_fen=deduct_result["balance_fen"],
        )

        # 推送微信通知"已自动扣款"
        try:
            customer_result = await self.db.execute(
                select(Customer).where(
                    Customer.id == uuid.UUID(customer_id),
                    Customer.tenant_id == self.tenant_id,
                )
            )
            customer = customer_result.scalar_one_or_none()

            if customer and customer.wechat_openid:
                try:
                    from services.tx_ops.src.services.notification_service import NotificationService  # noqa: E501
                except ImportError:
                    customer = None  # 跳过通知

                if customer:
                    notification_svc = NotificationService(
                        db=self.db,
                        tenant_id=str(self.tenant_id),
                    )
                    amount_yuan = final_amount_fen / 100
                    balance_yuan = deduct_result["balance_fen"] / 100
                    await notification_svc.send_wechat(
                        openid=customer.wechat_openid,
                        template_id="auto_pay_deducted",
                        data={
                            "first": {"value": "储值卡已自动扣款"},
                            "keyword1": {"value": f"¥{amount_yuan:.2f}"},
                            "keyword2": {"value": f"¥{balance_yuan:.2f}"},
                            "remark": {"value": "如有疑问请联系门店"},
                        },
                    )
        except (ConnectionError, TimeoutError, ValueError, RuntimeError) as exc:
            # 通知失败不影响扣款结果
            logger.warning(
                "auto_pay_notification_failed",
                order_id=order_id,
                error=str(exc),
            )

        return {
            "success": True,
            "card_id": target_card["card_id"],
            "deducted_fen": final_amount_fen,
            "balance_fen": deduct_result["balance_fen"],
        }

    @staticmethod
    def _method_to_category(method: str) -> str:
        """支付方式映射到支付类别"""
        mapping = {
            "cash": "现金",
            "wechat": "移动支付",
            "alipay": "移动支付",
            "unionpay": "银联卡",
            "member_balance": "会员消费",
            "credit_account": "挂账",
        }
        return mapping.get(method, "other")

    # ─────────────────────────────────────
    # 6. Table Transfer (转台)
    # ─────────────────────────────────────

    async def transfer_table(
        self,
        order_id: str,
        target_table_no: str,
        operator_id: Optional[str] = None,
    ) -> dict:
        """转台 — 校验目标桌空闲 → 更新Order → 释放原桌 → 锁新桌

        业务规则：
        1. 订单必须处于 pending/confirmed 状态
        2. 目标桌必须为 free 状态
        3. 原桌号记录到 order.table_transfer_from 以供追溯
        """
        order_uuid = uuid.UUID(order_id)
        order = await self._get_order(order_uuid)

        # 校验订单状态
        if order.status in (OrderStatus.completed.value, OrderStatus.cancelled.value):
            raise ValueError(f"订单状态 {order.status}，无法转台")

        old_table_no = order.table_number
        if not old_table_no:
            raise ValueError("订单无桌台信息，无法转台")

        if old_table_no == target_table_no:
            raise ValueError("目标桌与当前桌相同，无需转台")

        store_uuid = order.store_id

        # 查询目标桌台
        target_result = await self.db.execute(
            select(Table).where(
                Table.store_id == store_uuid,
                Table.table_no == target_table_no,
                Table.tenant_id == self.tenant_id,
                Table.is_active == True,  # noqa: E712
            )
        )
        target_table = target_result.scalar_one_or_none()
        if not target_table:
            raise ValueError(f"目标桌台不存在: {target_table_no}")

        if target_table.status != TableStatus.free.value:
            raise ValueError(
                f"目标桌台 {target_table_no} 当前状态 {target_table.status}，"
                f"不是空闲状态，无法转入"
            )

        # 释放原桌
        await self._release_table(str(store_uuid), old_table_no)

        # 锁定目标桌
        target_table.status = TableStatus.occupied.value
        target_table.current_order_id = order_uuid

        # 更新订单桌号 + 记录转台历史
        order.table_number = target_table_no
        order.table_transfer_from = old_table_no
        order.order_metadata = {
            **(order.order_metadata or {}),
            "last_transfer": {
                "from": old_table_no,
                "to": target_table_no,
                "operator_id": operator_id,
                "transferred_at": datetime.now(timezone.utc).isoformat(),
            },
        }

        await self.db.flush()

        logger.info(
            "table_transferred",
            order_id=order_id,
            order_no=order.order_no,
            from_table=old_table_no,
            to_table=target_table_no,
            operator_id=operator_id,
        )

        return {
            "order_id": order_id,
            "order_no": order.order_no,
            "from_table": old_table_no,
            "to_table": target_table_no,
            "status": order.status,
            "operator_id": operator_id,
        }
