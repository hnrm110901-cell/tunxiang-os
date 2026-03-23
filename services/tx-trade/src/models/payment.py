"""支付模型 — 多支付方式 + 退款"""
import uuid

from sqlalchemy import String, Integer, Float, Boolean, DateTime, Text, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase
from .enums import PaymentMethod, PaymentStatus, RefundType


class Payment(TenantBase):
    """支付记录 — 一笔订单可有多条支付（混合支付）"""
    __tablename__ = "payments"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False, index=True
    )
    payment_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="支付流水号")
    method: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PaymentMethod.cash.value
    )
    amount_fen: Mapped[int] = mapped_column(Integer, nullable=False, comment="支付金额(分)")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PaymentStatus.pending.value, index=True
    )

    # 实收属性
    is_actual_revenue: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="是否计入实收"
    )
    actual_revenue_ratio: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0,
        comment="实收比例(0-1)，例如团购券按面额的0.9计入实收"
    )
    payment_category: Mapped[str] = mapped_column(
        String(20), nullable=False, default="other",
        comment="支付类别：现金/移动支付/会员消费/团购/银联卡/银行卡/挂账/快充/免单/外卖支付/华彩会员/优惠券/其他"
    )

    # 第三方支付信息
    trade_no: Mapped[str | None] = mapped_column(String(128), comment="第三方交易号(微信/支付宝)")
    paid_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))

    # 挂账信息
    credit_account_name: Mapped[str | None] = mapped_column(String(100), comment="挂账单位/人")
    credit_account_phone: Mapped[str | None] = mapped_column(String(20))

    notes: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict | None] = mapped_column(JSON, default=dict)


class Refund(TenantBase):
    """退款记录"""
    __tablename__ = "refunds"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False, index=True
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id"), nullable=False
    )
    refund_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    refund_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RefundType.full.value
    )
    amount_fen: Mapped[int] = mapped_column(Integer, nullable=False, comment="退款金额(分)")
    reason: Mapped[str | None] = mapped_column(String(500))
    operator_id: Mapped[str | None] = mapped_column(String(50), comment="操作员ID")
    refunded_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))
    trade_no: Mapped[str | None] = mapped_column(String(128), comment="第三方退款交易号")
    extra: Mapped[dict | None] = mapped_column(JSON, default=dict)
