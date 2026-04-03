"""收银员交班服务 — 班次开始/现金清点/交班完成/报告查询

交班流程：start_handover → record_cash_count → finalize_handover → get_shift_summary
所有金额单位：分（fen）。
"""
import asyncio
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import Date, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events import TradeEventType, UniversalPublisher
from shared.ontology.src.entities import Order
from shared.ontology.src.enums import OrderStatus

from ..models.enums import PaymentStatus
from ..models.payment import Payment, Refund
from ..models.settlement import ShiftHandover

logger = structlog.get_logger()

# 现金面额对应分值（元 → 分）
DENOMINATION_TO_FEN = {
    "100": 10000,
    "50": 5000,
    "20": 2000,
    "10": 1000,
    "5": 500,
    "2": 200,
    "1": 100,
    "0.5": 50,
    "0.1": 10,
}

# 现金差异告警阈值：100元 = 10000分
CASH_VARIANCE_THRESHOLD_FEN = 10000


class ShiftHandoverService:
    """收银员交班服务

    覆盖交班全流程：开始交班 → 现金清点 → 完成交班 → 查看报告。
    """

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = uuid.UUID(tenant_id)

    async def start_handover(
        self,
        cashier_id: str,
        store_id: str,
    ) -> dict:
        """开始交班 — 创建交班记录，快照当前班次数据

        Args:
            cashier_id: 当前收银员ID
            store_id: 门店ID
        """
        store_uuid = uuid.UUID(store_id)

        # 快照当前班次数据：查询该收银员当班所有已完成订单
        summary = await self._snapshot_shift_data(cashier_id, store_uuid)

        handover = ShiftHandover(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            store_id=store_uuid,
            from_employee_id=cashier_id,
            to_employee_id="",  # 交班时再填
            orders_count=summary["total_orders"],
            revenue_fen=summary["total_revenue_fen"],
            cash_on_hand_fen=None,
            pending_issues=[],
            notes=None,
        )
        # 将快照数据存入 pending_issues 字段的 JSON 中（复用现有字段）
        handover.pending_issues = {
            "status": "started",
            "shift_snapshot": summary,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "cash_count": None,
            "finalized": False,
        }

        self.db.add(handover)
        await self.db.flush()

        logger.info(
            "shift_handover_started",
            handover_id=str(handover.id),
            cashier_id=cashier_id,
            store_id=store_id,
            total_orders=summary["total_orders"],
            total_revenue_fen=summary["total_revenue_fen"],
            tenant_id=str(self.tenant_id),
        )

        return {
            "handover_id": str(handover.id),
            "cashier_id": cashier_id,
            "store_id": store_id,
            "status": "started",
            "shift_snapshot": summary,
        }

    async def record_cash_count(
        self,
        handover_id: str,
        denominations: dict,
    ) -> dict:
        """录入实际现金清点

        Args:
            handover_id: 交班记录ID
            denominations: 按面额录入，如 {"100": 5, "50": 3, "20": 2, "10": 5, "1": 8}
                          key=面额(元字符串), value=张数
        """
        handover = await self._get_handover(handover_id)

        # 计算实际现金总额（分）
        actual_fen = 0
        denomination_detail = {}
        for denom_str, count in denominations.items():
            fen_per = DENOMINATION_TO_FEN.get(str(denom_str))
            if fen_per is None:
                raise ValueError(f"不支持的面额: {denom_str}")
            subtotal = fen_per * int(count)
            actual_fen += subtotal
            denomination_detail[str(denom_str)] = {
                "count": int(count),
                "subtotal_fen": subtotal,
            }

        handover.cash_on_hand_fen = actual_fen

        # 更新 pending_issues 中的 cash_count 数据
        details = handover.pending_issues or {}
        details["cash_count"] = {
            "denominations": denominations,
            "denomination_detail": denomination_detail,
            "actual_fen": actual_fen,
            "counted_at": datetime.now(timezone.utc).isoformat(),
        }
        details["status"] = "counting"
        handover.pending_issues = details

        await self.db.flush()

        logger.info(
            "cash_count_recorded",
            handover_id=handover_id,
            actual_fen=actual_fen,
            denominations=denominations,
            tenant_id=str(self.tenant_id),
        )

        return {
            "handover_id": handover_id,
            "cash_actual_fen": actual_fen,
            "denomination_detail": denomination_detail,
            "status": "counting",
        }

    async def finalize_handover(
        self,
        handover_id: str,
    ) -> dict:
        """完成交班 — 计算差异，生成交班报告

        自动计算：系统应有现金 vs 实际清点现金 → 差异
        差异超过阈值(100元)自动标记。
        """
        handover = await self._get_handover(handover_id)
        details = handover.pending_issues or {}

        if details.get("finalized"):
            raise ValueError(f"交班已完成: {handover_id}")

        if not details.get("cash_count"):
            raise ValueError(f"请先录入现金清点: {handover_id}")

        snapshot = details.get("shift_snapshot", {})
        cash_expected_fen = snapshot.get("cash_fen", 0)
        cash_actual_fen = handover.cash_on_hand_fen or 0
        variance_fen = cash_actual_fen - cash_expected_fen

        # 判断是否超过阈值
        variance_alert = abs(variance_fen) > CASH_VARIANCE_THRESHOLD_FEN
        status = "variance_alert" if variance_alert else "completed"

        # 更新记录
        details["status"] = status
        details["finalized"] = True
        details["finalized_at"] = datetime.now(timezone.utc).isoformat()
        details["variance"] = {
            "cash_expected_fen": cash_expected_fen,
            "cash_actual_fen": cash_actual_fen,
            "variance_fen": variance_fen,
            "variance_alert": variance_alert,
            "threshold_fen": CASH_VARIANCE_THRESHOLD_FEN,
        }
        handover.pending_issues = details

        await self.db.flush()

        asyncio.create_task(UniversalPublisher.publish(
            event_type=TradeEventType.SHIFT_HANDOVER,
            tenant_id=self.tenant_id,
            store_id=handover.store_id,
            entity_id=handover.id,
            event_data={
                "shift_id": str(handover.id),
                "from_employee_id": handover.from_employee_id,
                "to_employee_id": handover.to_employee_id,
            },
            source_service="tx-trade",
        ))

        report = {
            "handover_id": handover_id,
            "total_orders": handover.orders_count,
            "total_revenue_fen": handover.revenue_fen,
            "cash_expected_fen": cash_expected_fen,
            "cash_actual_fen": cash_actual_fen,
            "variance_fen": variance_fen,
            "variance_alert": variance_alert,
            "status": status,
        }

        logger.info(
            "shift_handover_finalized",
            handover_id=handover_id,
            variance_fen=variance_fen,
            variance_alert=variance_alert,
            status=status,
            tenant_id=str(self.tenant_id),
        )

        return report

    async def get_shift_summary(
        self,
        handover_id: str,
    ) -> dict:
        """获取交班报告摘要"""
        handover = await self._get_handover(handover_id)
        details = handover.pending_issues or {}
        snapshot = details.get("shift_snapshot", {})
        variance = details.get("variance", {})

        return {
            "handover_id": str(handover.id),
            "store_id": str(handover.store_id),
            "cashier_id": handover.from_employee_id,
            "status": details.get("status", "unknown"),
            "started_at": details.get("started_at"),
            "finalized_at": details.get("finalized_at"),
            "total_orders": handover.orders_count,
            "total_revenue_fen": handover.revenue_fen,
            "by_method": snapshot.get("by_method", {}),
            "cash_expected_fen": variance.get("cash_expected_fen", snapshot.get("cash_fen", 0)),
            "cash_actual_fen": handover.cash_on_hand_fen,
            "variance_fen": variance.get("variance_fen"),
            "variance_alert": variance.get("variance_alert", False),
            "cash_count_detail": details.get("cash_count"),
            "pending_issues": details.get("pending_items", []),
        }

    # ─────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────

    async def _get_handover(self, handover_id: str) -> ShiftHandover:
        result = await self.db.execute(
            select(ShiftHandover).where(
                ShiftHandover.id == uuid.UUID(handover_id),
                ShiftHandover.tenant_id == self.tenant_id,
            )
        )
        handover = result.scalar_one_or_none()
        if not handover:
            raise ValueError(f"交班记录不存在: {handover_id}")
        return handover

    async def _snapshot_shift_data(
        self,
        cashier_id: str,
        store_id: uuid.UUID,
    ) -> dict:
        """快照当前班次数据 — 汇总该收银员当日已完成订单"""
        today = datetime.now(timezone.utc).date()

        # 查当日该收银员所有已完成订单
        orders_result = await self.db.execute(
            select(Order).where(
                Order.store_id == store_id,
                Order.tenant_id == self.tenant_id,
                Order.status == OrderStatus.completed.value,
                Order.waiter_id == cashier_id,
                cast(Order.order_time, Date) == today,
            )
        )
        orders = orders_result.scalars().all()
        order_ids = [o.id for o in orders]

        total_revenue = sum(o.final_amount_fen or 0 for o in orders)
        total_discount = sum(o.discount_amount_fen or 0 for o in orders)

        # 按支付方式汇总
        method_totals = {
            "cash": 0,
            "wechat": 0,
            "alipay": 0,
            "unionpay": 0,
            "credit_account": 0,
            "member_balance": 0,
        }

        total_refund = 0
        if order_ids:
            payments_result = await self.db.execute(
                select(Payment).where(
                    Payment.order_id.in_(order_ids),
                    Payment.status.in_([
                        PaymentStatus.paid.value,
                        PaymentStatus.partial_refund.value,
                    ]),
                )
            )
            payments = payments_result.scalars().all()
            for p in payments:
                if p.method in method_totals:
                    method_totals[p.method] += p.amount_fen

            # 退款汇总
            refunds_result = await self.db.execute(
                select(Refund).where(Refund.order_id.in_(order_ids))
            )
            refunds = refunds_result.scalars().all()
            total_refund = sum(r.amount_fen for r in refunds)

        return {
            "total_orders": len(orders),
            "total_revenue_fen": total_revenue,
            "total_discount_fen": total_discount,
            "total_refund_fen": total_refund,
            "cash_fen": method_totals["cash"],
            "by_method": method_totals,
        }
