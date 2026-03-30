"""AA 拆账结账服务 — 按人头均分 / 按菜品拆分 / 单人结账

对标 Square Split Tender。
所有金额单位：分（fen）。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Order, OrderItem
from shared.ontology.src.enums import OrderStatus

logger = structlog.get_logger()


# ─── 拆账单内存存储（轻量模拟，生产环境替换为数据库表） ───


class _SplitStore:
    """AA拆账存储"""

    _splits: dict[str, dict] = {}  # split_id -> split_data
    _by_order: dict[str, str] = {}  # order_id -> split_id

    @classmethod
    def save(cls, split_id: str, data: dict) -> None:
        cls._splits[split_id] = data
        cls._by_order[data["order_id"]] = split_id

    @classmethod
    def get(cls, split_id: str) -> Optional[dict]:
        return cls._splits.get(split_id)

    @classmethod
    def get_by_order(cls, order_id: str) -> Optional[dict]:
        sid = cls._by_order.get(order_id)
        return cls._splits.get(sid) if sid else None


class SplitSettleService:
    """AA 拆账结账服务

    支持两种拆账模式：
    - 按人头均分：total / N，余数加到第一人
    - 按菜品拆分：每人付自己点的菜，公共菜品均摊
    """

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = uuid.UUID(tenant_id)

    async def split_by_person(
        self,
        order_id: str,
        person_count: int,
    ) -> dict:
        """按人头均分

        total_amount / person_count，余数加到第一人。
        返回 N 个子账单，每个可独立支付。
        """
        if person_count < 2:
            raise ValueError("AA拆账至少需要2人")

        order = await self._get_order(order_id)
        if order.status == OrderStatus.completed.value:
            raise ValueError("订单已结算，无法拆账")
        if order.status == OrderStatus.cancelled.value:
            raise ValueError("订单已取消，无法拆账")

        final_amount: int = order.final_amount_fen
        if final_amount <= 0:
            raise ValueError("订单金额为0，无法拆账")

        # 均分，余数加到第一人
        per_person: int = final_amount // person_count
        remainder: int = final_amount % person_count

        split_id = str(uuid.uuid4())
        bills: list[dict] = []

        for i in range(person_count):
            bill_id = str(uuid.uuid4())
            amount = per_person + (remainder if i == 0 else 0)
            bills.append({
                "bill_id": bill_id,
                "person_index": i,
                "amount_fen": amount,
                "paid": False,
                "payment_result": None,
            })

        split_data = {
            "split_id": split_id,
            "order_id": order_id,
            "tenant_id": str(self.tenant_id),
            "mode": "by_person",
            "person_count": person_count,
            "total_amount_fen": final_amount,
            "bills": bills,
            "all_paid": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _SplitStore.save(split_id, split_data)

        logger.info(
            "split_by_person_created",
            split_id=split_id,
            order_id=order_id,
            person_count=person_count,
            total_amount_fen=final_amount,
            per_person_fen=per_person,
            remainder_fen=remainder,
        )

        return {
            "split_id": split_id,
            "order_id": order_id,
            "mode": "by_person",
            "person_count": person_count,
            "total_amount_fen": final_amount,
            "bills": [
                {
                    "bill_id": b["bill_id"],
                    "person_index": b["person_index"],
                    "amount_fen": b["amount_fen"],
                    "paid": b["paid"],
                }
                for b in bills
            ],
        }

    async def split_by_item(
        self,
        order_id: str,
        assignments: list[dict],
    ) -> dict:
        """按菜品拆分

        Args:
            assignments: [{"person_id": "xxx", "item_ids": ["item1", "item2"]}]

        每人只付自己点的菜。公共菜品（无人认领的，如茶位费）均摊。
        """
        if len(assignments) < 2:
            raise ValueError("按菜品拆账至少需要2人")

        order = await self._get_order(order_id)
        if order.status == OrderStatus.completed.value:
            raise ValueError("订单已结算，无法拆账")
        if order.status == OrderStatus.cancelled.value:
            raise ValueError("订单已取消，无法拆账")

        # 加载所有明细
        items_result = await self.db.execute(
            select(OrderItem).where(
                OrderItem.order_id == uuid.UUID(order_id),
            )
        )
        all_items = {str(i.id): i for i in items_result.scalars().all()}

        # 汇总每个人认领的菜品金额
        claimed_item_ids: set[str] = set()
        person_totals: dict[str, int] = {}

        for assignment in assignments:
            person_id: str = assignment["person_id"]
            item_ids: list[str] = assignment.get("item_ids", [])
            person_total = 0

            for iid in item_ids:
                if iid not in all_items:
                    raise ValueError(f"菜品明细不存在: {iid}")
                if iid in claimed_item_ids:
                    raise ValueError(f"菜品 {iid} 已被其他人认领")
                claimed_item_ids.add(iid)
                person_total += all_items[iid].subtotal_fen

            person_totals[person_id] = person_total

        # 计算公共菜品（未被认领的）— 均摊
        unclaimed_total = sum(
            item.subtotal_fen
            for iid, item in all_items.items()
            if iid not in claimed_item_ids
        )

        person_count = len(assignments)
        shared_per_person: int = unclaimed_total // person_count
        shared_remainder: int = unclaimed_total % person_count

        # 构建子账单
        split_id = str(uuid.uuid4())
        bills: list[dict] = []

        for i, assignment in enumerate(assignments):
            person_id = assignment["person_id"]
            bill_id = str(uuid.uuid4())
            own_amount = person_totals.get(person_id, 0)
            shared_amount = shared_per_person + (shared_remainder if i == 0 else 0)
            total_amount = own_amount + shared_amount

            bills.append({
                "bill_id": bill_id,
                "person_id": person_id,
                "person_index": i,
                "own_items_fen": own_amount,
                "shared_items_fen": shared_amount,
                "amount_fen": total_amount,
                "item_ids": assignment.get("item_ids", []),
                "paid": False,
                "payment_result": None,
            })

        # 校验拆账总额 == 订单应付
        split_total = sum(b["amount_fen"] for b in bills)
        if split_total != order.final_amount_fen:
            # 优惠差额修正：可能因为 discount_amount_fen 导致差异
            # 将差额从第一人调整
            diff = order.final_amount_fen - split_total
            bills[0]["amount_fen"] += diff
            bills[0]["shared_items_fen"] += diff

        split_data = {
            "split_id": split_id,
            "order_id": order_id,
            "tenant_id": str(self.tenant_id),
            "mode": "by_item",
            "person_count": person_count,
            "total_amount_fen": order.final_amount_fen,
            "shared_items_total_fen": unclaimed_total,
            "bills": bills,
            "all_paid": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _SplitStore.save(split_id, split_data)

        logger.info(
            "split_by_item_created",
            split_id=split_id,
            order_id=order_id,
            person_count=person_count,
            shared_items_total_fen=unclaimed_total,
        )

        return {
            "split_id": split_id,
            "order_id": order_id,
            "mode": "by_item",
            "person_count": person_count,
            "total_amount_fen": order.final_amount_fen,
            "shared_items_total_fen": unclaimed_total,
            "bills": [
                {
                    "bill_id": b["bill_id"],
                    "person_id": b.get("person_id"),
                    "person_index": b["person_index"],
                    "own_items_fen": b.get("own_items_fen", 0),
                    "shared_items_fen": b.get("shared_items_fen", 0),
                    "amount_fen": b["amount_fen"],
                    "paid": b["paid"],
                }
                for b in bills
            ],
        }

    async def settle_split(
        self,
        split_id: str,
        bill_id: str,
        payment_method: str,
        amount_fen: int,
        auth_code: Optional[str] = None,
    ) -> dict:
        """单人结账 — 为拆账中某一个子账单付款

        调用 PaymentGateway 处理支付。
        全部人付完后自动完成订单。
        """
        split_data = _SplitStore.get(split_id)
        if not split_data:
            raise ValueError(f"拆账记录不存在: {split_id}")

        if split_data["tenant_id"] != str(self.tenant_id):
            raise ValueError("租户不匹配")

        if split_data["all_paid"]:
            raise ValueError("所有子账单已付清")

        # 查找目标子账单
        target_bill: Optional[dict] = None
        for bill in split_data["bills"]:
            if bill["bill_id"] == bill_id:
                target_bill = bill
                break

        if not target_bill:
            raise ValueError(f"子账单不存在: {bill_id}")

        if target_bill["paid"]:
            raise ValueError(f"子账单 {bill_id} 已付款")

        if amount_fen < target_bill["amount_fen"]:
            raise ValueError(
                f"支付金额 {amount_fen} 不足，子账单应付 {target_bill['amount_fen']}"
            )

        # 调用 PaymentGateway 创建支付
        from .payment_gateway import PaymentGateway

        order_id = split_data["order_id"]
        gateway = PaymentGateway(
            db=self.db,
            tenant_id=str(self.tenant_id),
        )

        pay_result = await gateway.create_payment(
            order_id=order_id,
            method=payment_method,
            amount_fen=target_bill["amount_fen"],
            auth_code=auth_code,
        )

        # 标记子账单已付
        target_bill["paid"] = True
        target_bill["payment_result"] = pay_result

        # 检查是否全部付完
        all_paid = all(b["paid"] for b in split_data["bills"])
        split_data["all_paid"] = all_paid

        _SplitStore.save(split_id, split_data)

        logger.info(
            "split_bill_settled",
            split_id=split_id,
            bill_id=bill_id,
            payment_method=payment_method,
            amount_fen=target_bill["amount_fen"],
            all_paid=all_paid,
        )

        # 全部付完 → 自动完成订单
        if all_paid:
            await self._complete_order(order_id)

        return {
            "split_id": split_id,
            "bill_id": bill_id,
            "amount_fen": target_bill["amount_fen"],
            "payment_result": pay_result,
            "all_paid": all_paid,
            "remaining_bills": [
                {
                    "bill_id": b["bill_id"],
                    "amount_fen": b["amount_fen"],
                    "paid": b["paid"],
                }
                for b in split_data["bills"]
                if not b["paid"]
            ],
        }

    async def get_split_status(self, split_id: str) -> dict:
        """查询拆账状态"""
        split_data = _SplitStore.get(split_id)
        if not split_data:
            raise ValueError(f"拆账记录不存在: {split_id}")

        return {
            "split_id": split_data["split_id"],
            "order_id": split_data["order_id"],
            "mode": split_data["mode"],
            "total_amount_fen": split_data["total_amount_fen"],
            "all_paid": split_data["all_paid"],
            "paid_count": sum(1 for b in split_data["bills"] if b["paid"]),
            "total_count": len(split_data["bills"]),
            "paid_amount_fen": sum(
                b["amount_fen"] for b in split_data["bills"] if b["paid"]
            ),
            "remaining_amount_fen": sum(
                b["amount_fen"] for b in split_data["bills"] if not b["paid"]
            ),
            "bills": [
                {
                    "bill_id": b["bill_id"],
                    "person_index": b["person_index"],
                    "amount_fen": b["amount_fen"],
                    "paid": b["paid"],
                }
                for b in split_data["bills"]
            ],
        }

    # ─── 内部方法 ───

    async def _get_order(self, order_id: str) -> Order:
        result = await self.db.execute(
            select(Order).where(
                Order.id == uuid.UUID(order_id),
                Order.tenant_id == self.tenant_id,
            )
        )
        order = result.scalar_one_or_none()
        if not order:
            raise ValueError(f"订单不存在: {order_id}")
        return order

    async def _complete_order(self, order_id: str) -> None:
        """全部子账单付完后，完成订单并释放桌台"""
        from sqlalchemy import update
        from ..models.tables import Table
        from ..models.enums import TableStatus

        order = await self._get_order(order_id)
        order.status = OrderStatus.completed.value
        order.completed_at = datetime.now(timezone.utc)

        # 释放桌台
        if order.table_number:
            await self.db.execute(
                update(Table)
                .where(
                    Table.store_id == order.store_id,
                    Table.table_no == order.table_number,
                )
                .values(status=TableStatus.free.value, current_order_id=None)
            )

        await self.db.flush()

        logger.info(
            "split_order_completed",
            order_id=order_id,
            order_no=order.order_no,
        )

        # 异步触发支付后推券（不阻塞）
        try:
            from .post_payment_service import PostPaymentService

            post_svc = PostPaymentService(self.db, str(self.tenant_id))
            customer_id = str(order.customer_id) if order.customer_id else None
            if customer_id:
                await post_svc.trigger_post_payment(order_id, customer_id)
        except (ImportError, ValueError, RuntimeError) as exc:
            logger.warning(
                "post_payment_trigger_failed_in_split",
                order_id=order_id,
                error=str(exc),
            )
