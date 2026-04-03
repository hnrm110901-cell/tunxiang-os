"""结算模型 — 日结/班结/交接班"""
import uuid

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase

from .enums import SettlementType


class Settlement(TenantBase):
    """日结/班结记录"""
    __tablename__ = "settlements"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True
    )
    settlement_date: Mapped[str] = mapped_column(Date, nullable=False, index=True)
    settlement_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SettlementType.daily.value
    )

    # 汇总金额（分）
    total_revenue_fen: Mapped[int] = mapped_column(Integer, default=0, comment="总营收(分)")
    total_discount_fen: Mapped[int] = mapped_column(Integer, default=0, comment="总折扣(分)")
    total_refund_fen: Mapped[int] = mapped_column(Integer, default=0, comment="总退款(分)")
    net_revenue_fen: Mapped[int] = mapped_column(Integer, default=0, comment="净营收(分)")

    # 按支付方式汇总
    cash_fen: Mapped[int] = mapped_column(Integer, default=0)
    wechat_fen: Mapped[int] = mapped_column(Integer, default=0)
    alipay_fen: Mapped[int] = mapped_column(Integer, default=0)
    unionpay_fen: Mapped[int] = mapped_column(Integer, default=0)
    credit_fen: Mapped[int] = mapped_column(Integer, default=0, comment="挂账(分)")
    member_balance_fen: Mapped[int] = mapped_column(Integer, default=0, comment="会员余额(分)")

    # 订单统计
    total_orders: Mapped[int] = mapped_column(Integer, default=0)
    total_guests: Mapped[int] = mapped_column(Integer, default=0)
    avg_per_guest_fen: Mapped[int] = mapped_column(Integer, default=0, comment="客单价(分)")

    # 现金盘点
    cash_expected_fen: Mapped[int] = mapped_column(Integer, default=0, comment="应有现金(分)")
    cash_actual_fen: Mapped[int | None] = mapped_column(Integer, comment="实际现金(分)")
    cash_diff_fen: Mapped[int | None] = mapped_column(Integer, comment="现金差异(分)")

    operator_id: Mapped[str | None] = mapped_column(String(50), comment="结算操作员")
    settled_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict | None] = mapped_column(JSON, default=dict)


class ShiftHandover(TenantBase):
    """交接班记录"""
    __tablename__ = "shift_handovers"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True
    )
    from_employee_id: Mapped[str] = mapped_column(String(50), nullable=False)
    to_employee_id: Mapped[str] = mapped_column(String(50), nullable=False)
    handover_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # 交接时段汇总
    orders_count: Mapped[int] = mapped_column(Integer, default=0)
    revenue_fen: Mapped[int] = mapped_column(Integer, default=0)
    cash_on_hand_fen: Mapped[int | None] = mapped_column(Integer, comment="交接时现金(分)")

    pending_issues: Mapped[dict | None] = mapped_column(JSON, default=list, comment="待处理事项列表")
    notes: Mapped[str | None] = mapped_column(String(1000))
