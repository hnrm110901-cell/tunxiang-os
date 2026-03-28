"""班次对账服务 — 逐笔核对/现金长短款/可疑交易标记

对账 = 系统收款记录 vs 支付渠道回单，逐笔匹配。
所有金额单位：分（fen）。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select, and_, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Order
from shared.ontology.src.enums import OrderStatus
from ..models.settlement import ShiftHandover
from ..models.payment import Payment, Refund
from ..models.enums import PaymentStatus

logger = structlog.get_logger()

# 退款异常阈值：单笔退款占订单比例超过此值标记可疑
REFUND_RATIO_THRESHOLD = 0.5
# 折扣异常阈值：折扣率超过此值标记可疑
DISCOUNT_RATIO_THRESHOLD = 0.3
# 现金差异告警阈值（分）= 100元
CASH_VARIANCE_THRESHOLD_FEN = 10000


class ShiftReconciliationService:
    """班次对账服务

    逐笔核对系统收款 vs 支付渠道回单，发现差异和可疑交易。
    """

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = uuid.UUID(tenant_id)

    async def reconcile_shift(
        self,
        handover_id: str,
    ) -> dict:
        """逐笔核对：系统收款 vs 支付渠道回单

        对每笔支付记录：
        - 有 trade_no → 标记为 matched（已有渠道回单号）
        - 无 trade_no 且非现金 → 标记为 unmatched
        - 现金支付 → 跳过（现金通过清点对账）
        """
        handover = await self._get_handover(handover_id)
        details = handover.pending_issues or {}
        snapshot = details.get("shift_snapshot", {})

        # 查该交班关联的所有订单的支付记录
        order_ids = await self._get_shift_order_ids(handover)
        if not order_ids:
            return {
                "handover_id": handover_id,
                "matched_count": 0,
                "unmatched_count": 0,
                "unmatched_items": [],
                "total_checked": 0,
            }

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

        matched = []
        unmatched = []

        for p in payments:
            # 现金支付不走渠道对账
            if p.method == "cash":
                continue

            item = {
                "payment_id": str(p.id),
                "payment_no": p.payment_no,
                "order_id": str(p.order_id),
                "method": p.method,
                "amount_fen": p.amount_fen,
                "trade_no": p.trade_no,
                "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            }

            if p.trade_no:
                matched.append(item)
            else:
                unmatched.append(item)

        result = {
            "handover_id": handover_id,
            "matched_count": len(matched),
            "unmatched_count": len(unmatched),
            "unmatched_items": unmatched,
            "total_checked": len(matched) + len(unmatched),
        }

        logger.info(
            "shift_reconciled",
            handover_id=handover_id,
            matched=len(matched),
            unmatched=len(unmatched),
            tenant_id=str(self.tenant_id),
        )

        return result

    async def get_cash_variance_detail(
        self,
        handover_id: str,
    ) -> dict:
        """现金长短款明细

        返回：系统应有现金、实际清点现金、差异金额、面额明细。
        """
        handover = await self._get_handover(handover_id)
        details = handover.pending_issues or {}
        snapshot = details.get("shift_snapshot", {})
        cash_count = details.get("cash_count", {})
        variance_info = details.get("variance", {})

        cash_expected_fen = variance_info.get(
            "cash_expected_fen", snapshot.get("cash_fen", 0)
        )
        cash_actual_fen = handover.cash_on_hand_fen or 0
        variance_fen = cash_actual_fen - cash_expected_fen

        # 判断长款/短款
        if variance_fen > 0:
            variance_type = "surplus"  # 长款
            variance_desc = f"长款 {variance_fen / 100:.2f} 元"
        elif variance_fen < 0:
            variance_type = "shortage"  # 短款
            variance_desc = f"短款 {abs(variance_fen) / 100:.2f} 元"
        else:
            variance_type = "balanced"
            variance_desc = "现金无差异"

        return {
            "handover_id": handover_id,
            "cash_expected_fen": cash_expected_fen,
            "cash_actual_fen": cash_actual_fen,
            "variance_fen": variance_fen,
            "variance_type": variance_type,
            "variance_desc": variance_desc,
            "variance_alert": abs(variance_fen) > CASH_VARIANCE_THRESHOLD_FEN,
            "denomination_detail": cash_count.get("denomination_detail", {}),
            "counted_at": cash_count.get("counted_at"),
        }

    async def flag_suspicious_transactions(
        self,
        handover_id: str,
    ) -> dict:
        """可疑交易标记 — 退款异常、折扣异常等

        检测规则：
        1. 退款异常：单笔退款金额 > 订单金额的 50%
        2. 折扣异常：折扣率 > 30%
        3. 现金支付异常：单笔现金 > 500元 且无备注
        """
        handover = await self._get_handover(handover_id)
        order_ids = await self._get_shift_order_ids(handover)

        suspicious = []

        if not order_ids:
            return {
                "handover_id": handover_id,
                "suspicious_count": 0,
                "suspicious_items": [],
            }

        # 1. 检查退款异常
        refunds_result = await self.db.execute(
            select(Refund).where(Refund.order_id.in_(order_ids))
        )
        refunds = refunds_result.scalars().all()

        for r in refunds:
            # 查对应订单
            order_result = await self.db.execute(
                select(Order).where(Order.id == r.order_id)
            )
            order = order_result.scalar_one_or_none()
            if order and order.final_amount_fen > 0:
                ratio = r.amount_fen / order.final_amount_fen
                if ratio > REFUND_RATIO_THRESHOLD:
                    suspicious.append({
                        "type": "refund_anomaly",
                        "severity": "high",
                        "order_id": str(r.order_id),
                        "refund_id": str(r.id),
                        "refund_amount_fen": r.amount_fen,
                        "order_amount_fen": order.final_amount_fen,
                        "ratio": round(ratio, 4),
                        "reason": r.reason,
                        "message": f"退款 {r.amount_fen / 100:.2f}元 占订单 {ratio:.0%}，超过阈值 {REFUND_RATIO_THRESHOLD:.0%}",
                    })

        # 2. 检查折扣异常
        orders_result = await self.db.execute(
            select(Order).where(
                Order.id.in_(order_ids),
                Order.tenant_id == self.tenant_id,
            )
        )
        orders = orders_result.scalars().all()

        for o in orders:
            if o.total_amount_fen > 0 and o.discount_amount_fen > 0:
                discount_rate = o.discount_amount_fen / o.total_amount_fen
                if discount_rate > DISCOUNT_RATIO_THRESHOLD:
                    suspicious.append({
                        "type": "discount_anomaly",
                        "severity": "medium",
                        "order_id": str(o.id),
                        "order_no": o.order_no,
                        "total_amount_fen": o.total_amount_fen,
                        "discount_amount_fen": o.discount_amount_fen,
                        "discount_rate": round(discount_rate, 4),
                        "message": f"折扣率 {discount_rate:.0%} 超过阈值 {DISCOUNT_RATIO_THRESHOLD:.0%}",
                    })

        # 3. 检查大额现金支付异常
        payments_result = await self.db.execute(
            select(Payment).where(
                Payment.order_id.in_(order_ids),
                Payment.method == "cash",
                Payment.amount_fen > 50000,  # > 500元
            )
        )
        large_cash = payments_result.scalars().all()

        for p in large_cash:
            if not p.notes:
                suspicious.append({
                    "type": "large_cash_no_note",
                    "severity": "low",
                    "order_id": str(p.order_id),
                    "payment_id": str(p.id),
                    "amount_fen": p.amount_fen,
                    "message": f"大额现金 {p.amount_fen / 100:.2f}元 无备注说明",
                })

        result = {
            "handover_id": handover_id,
            "suspicious_count": len(suspicious),
            "suspicious_items": suspicious,
        }

        logger.info(
            "suspicious_transactions_flagged",
            handover_id=handover_id,
            count=len(suspicious),
            tenant_id=str(self.tenant_id),
        )

        return result

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

    async def _get_shift_order_ids(
        self,
        handover: ShiftHandover,
    ) -> list[uuid.UUID]:
        """获取该交班关联的所有订单ID"""
        today = datetime.now(timezone.utc).date()

        orders_result = await self.db.execute(
            select(Order.id).where(
                Order.store_id == handover.store_id,
                Order.tenant_id == self.tenant_id,
                Order.status == OrderStatus.completed.value,
                Order.waiter_id == handover.from_employee_id,
                cast(Order.order_time, Date) == today,
            )
        )
        return [row[0] for row in orders_result.all()]
