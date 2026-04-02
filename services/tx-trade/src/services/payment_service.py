"""支付服务 — 多方式支付 + 退款"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.enums import PaymentStatus, RefundType
from ..models.payment import Payment, Refund

logger = structlog.get_logger()


def _gen_payment_no() -> str:
    now = datetime.now(timezone.utc)
    return f"PAY{now.strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"


def _gen_refund_no() -> str:
    now = datetime.now(timezone.utc)
    return f"REF{now.strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"


class PaymentService:
    """支付服务"""

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = uuid.UUID(tenant_id)

    async def create_payment(
        self,
        order_id: str,
        method: str,
        amount_fen: int,
        trade_no: Optional[str] = None,
        credit_account_name: Optional[str] = None,
    ) -> dict:
        """创建支付记录"""
        payment = Payment(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            order_id=uuid.UUID(order_id),
            payment_no=_gen_payment_no(),
            method=method,
            amount_fen=amount_fen,
            status=PaymentStatus.paid.value,
            trade_no=trade_no,
            paid_at=datetime.now(timezone.utc),
            credit_account_name=credit_account_name,
        )
        self.db.add(payment)
        await self.db.flush()

        logger.info("payment_created", payment_no=payment.payment_no, method=method, amount_fen=amount_fen)
        return {
            "payment_id": str(payment.id),
            "payment_no": payment.payment_no,
            "status": payment.status,
        }

    async def process_refund(
        self,
        order_id: str,
        payment_id: str,
        amount_fen: int,
        refund_type: str = RefundType.full.value,
        reason: str = "",
        operator_id: Optional[str] = None,
    ) -> dict:
        """处理退款 — 支持整单退和部分退"""
        # 校验支付记录
        result = await self.db.execute(
            select(Payment).where(Payment.id == uuid.UUID(payment_id))
        )
        payment = result.scalar_one_or_none()
        if not payment:
            raise ValueError(f"Payment not found: {payment_id}")

        if amount_fen > payment.amount_fen:
            raise ValueError("Refund amount exceeds payment amount")

        refund = Refund(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            order_id=uuid.UUID(order_id),
            payment_id=uuid.UUID(payment_id),
            refund_no=_gen_refund_no(),
            refund_type=refund_type,
            amount_fen=amount_fen,
            reason=reason,
            operator_id=operator_id,
            refunded_at=datetime.now(timezone.utc),
        )
        self.db.add(refund)

        # 更新支付状态
        new_status = PaymentStatus.refunded.value if amount_fen == payment.amount_fen else PaymentStatus.partial_refund.value
        payment.status = new_status

        await self.db.flush()
        logger.info("refund_processed", refund_no=refund.refund_no, amount_fen=amount_fen)
        return {
            "refund_id": str(refund.id),
            "refund_no": refund.refund_no,
            "status": new_status,
        }

    async def get_order_payments(self, order_id: str) -> list[dict]:
        """查询订单所有支付记录"""
        result = await self.db.execute(
            select(Payment).where(Payment.order_id == uuid.UUID(order_id))
        )
        payments = result.scalars().all()
        return [
            {
                "payment_id": str(p.id),
                "payment_no": p.payment_no,
                "method": p.method,
                "amount_fen": p.amount_fen,
                "status": p.status,
                "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            }
            for p in payments
        ]
