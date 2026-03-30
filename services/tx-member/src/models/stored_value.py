"""储值卡模型 — 预付费/充值/消费/退款/赠送金

金额单位：分（fen），禁止使用 float 存金额。
v2: 增加 main_balance_fen、scope_type/scope_id、expiry_date、StoredValueRechargePlan
"""
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class StoredValueCard(TenantBase):
    """储值卡主表"""
    __tablename__ = "stored_value_cards"

    card_no: Mapped[str] = mapped_column(
        String(40), unique=True, nullable=False, index=True,
        comment="唯一卡号 SV-{YYYYMMDD}-{6位}",
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False, index=True,
    )
    store_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), comment="开卡门店，NULL=总部开卡",
    )

    # 余额字段（分）
    balance_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="当前总余额=本金+赠送(分)",
    )
    main_balance_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="本金余额(分)",
    )
    gift_balance_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="赠送余额(分)",
    )

    # 累计统计
    total_recharged_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="累计充值(分)",
    )
    total_consumed_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="累计消费(分)",
    )
    total_refunded_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="累计退款(分)",
    )

    # 使用范围策略
    scope_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brand",
        comment="store=仅本店 | brand=品牌内互通 | group=全集团",
    )
    scope_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        comment="scope_type=store时存store_id，brand时存brand_id，group时为NULL",
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active",
        comment="active | frozen | expired | cancelled",
    )
    expiry_date: Mapped[date | None] = mapped_column(
        Date, comment="过期日期，NULL=永不过期",
    )

    # 元数据
    remark: Mapped[str | None] = mapped_column(String(255))
    # 向后兼容字段（v1遗留）
    card_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="personal",
        comment="personal/corporate/gift（v1遗留）",
    )
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    operator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), comment="开卡操作员",
    )
    extra: Mapped[dict | None] = mapped_column(JSON, default=dict)

    __table_args__ = (
        Index("idx_svc_customer_id", "customer_id", "tenant_id"),
        Index("idx_svc_card_no", "card_no"),
        {"comment": "储值卡主表"},
    )


class StoredValueTransaction(TenantBase):
    """储值卡交易流水"""
    __tablename__ = "stored_value_transactions"

    card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stored_value_cards.id"), nullable=False, index=True,
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), comment="冗余存储便于查询",
    )
    store_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), comment="发生门店",
    )

    txn_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="recharge|consume|refund|gift_adjust|freeze|unfreeze",
    )
    amount_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="变动金额（正=增加，负=减少）",
    )
    main_amount_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="本金变动(分)",
    )
    gift_amount_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="赠送余额变动(分)",
    )
    balance_after_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="变动后总余额快照(分)",
    )
    # 向后兼容
    gift_balance_after_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="变动后赠送余额快照(v1遗留)",
    )

    # 关联业务
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), comment="消费时关联订单ID",
    )
    recharge_plan_id: Mapped[str | None] = mapped_column(
        String(50), comment="充值套餐ID",
    )

    operator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), comment="操作员工",
    )
    remark: Mapped[str | None] = mapped_column(String(255))
    extra: Mapped[dict | None] = mapped_column(JSON, default=dict)

    __table_args__ = (
        Index("idx_svt_card_id", "card_id", "created_at"),
        Index("idx_svt_order_id", "order_id"),
        {"comment": "储值卡交易流水"},
    )


class StoredValueRechargePlan(TenantBase):
    """充值套餐（充500送50）"""
    __tablename__ = "stored_value_recharge_plans"

    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="套餐名称")
    recharge_amount_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="需要充值金额(分)",
    )
    gift_amount_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="赠送金额(分)",
    )
    scope_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brand",
        comment="适用范围 store|brand|group",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remark: Mapped[str | None] = mapped_column(String(255))

    __table_args__ = ({"comment": "储值卡充值套餐"},)


# ---------------------------------------------------------------------------
# 向后兼容别名（v1遗留名称）
# ---------------------------------------------------------------------------
class RechargeRule(TenantBase):
    """充值赠送规则（v1遗留，新代码请使用 StoredValueRechargePlan）"""
    __tablename__ = "recharge_rules"

    rule_name: Mapped[str] = mapped_column(String(100), nullable=False)
    recharge_amount_fen: Mapped[int] = mapped_column(Integer, nullable=False, comment="充值金额(分)")
    gift_amount_fen: Mapped[int] = mapped_column(Integer, nullable=False, comment="赠送金额(分)")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    store_ids: Mapped[list | None] = mapped_column(JSON, comment="适用门店，null=全部")

    __table_args__ = ({"comment": "充值赠送规则（v1遗留）"},)
