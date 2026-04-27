"""资金分账模型 — 分账规则 / 分账流水 / 结算批次

支持平台方/品牌方/加盟商之间的交易资金自动分账。

表：
  split_rules       — 分账规则（按门店配置费率）
  split_ledgers     — 分账流水（每笔订单的分账明细）
  settlement_batches — 结算批次（按周期汇总结算）
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .cost_snapshot import Base


class SplitRule(Base):
    """分账规则

    rule_type 枚举：
    - platform_fee   : 平台技术服务费
    - brand_royalty   : 品牌使用费/管理费
    - franchise_share : 加盟商分成

    rate_permil: 费率（千分比），如 50 表示 5.0%
    fixed_fee_fen: 固定费用（分），每笔订单固定扣除
    """

    __tablename__ = "split_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    rule_type: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="规则类型: platform_fee/brand_royalty/franchise_share"
    )
    rate_permil: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="费率千分比，50=5.0%")
    fixed_fee_fen: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="固定费用（分）")

    effective_from: Mapped[date] = mapped_column(Date, nullable=False, comment="生效起始日期")
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True, comment="生效截止日期，NULL表示长期有效")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否启用")

    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_split_rules_tenant_store", "tenant_id", "store_id"),
        Index("ix_split_rules_tenant_type", "tenant_id", "rule_type"),
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "store_id": str(self.store_id),
            "rule_type": self.rule_type,
            "rate_permil": self.rate_permil,
            "fixed_fee_fen": self.fixed_fee_fen,
            "effective_from": str(self.effective_from),
            "effective_to": str(self.effective_to) if self.effective_to else None,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SplitLedger(Base):
    """分账流水 — 每笔订单的分账明细

    status 枚举：
    - pending  : 待结算
    - settled  : 已结算
    - failed   : 分账失败
    """

    __tablename__ = "split_ledgers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    total_amount_fen: Mapped[int] = mapped_column(Integer, nullable=False, comment="订单总金额（分）")
    platform_fee_fen: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="平台技术服务费（分）")
    brand_royalty_fen: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="品牌使用费（分）")
    franchise_share_fen: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="加盟商分成（分）")
    net_settlement_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="净结算金额（分）= total - platform_fee - brand_royalty"
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", comment="状态: pending/settled/failed"
    )
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="结算完成时间")
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, comment="所属结算批次ID")

    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_split_ledgers_tenant_order", "tenant_id", "order_id"),
        Index("ix_split_ledgers_tenant_store", "tenant_id", "store_id"),
        Index("ix_split_ledgers_tenant_status", "tenant_id", "status"),
        Index("ix_split_ledgers_tenant_batch", "tenant_id", "batch_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "order_id": str(self.order_id),
            "payment_id": str(self.payment_id) if self.payment_id else None,
            "store_id": str(self.store_id),
            "total_amount_fen": self.total_amount_fen,
            "platform_fee_fen": self.platform_fee_fen,
            "brand_royalty_fen": self.brand_royalty_fen,
            "franchise_share_fen": self.franchise_share_fen,
            "net_settlement_fen": self.net_settlement_fen,
            "status": self.status,
            "settled_at": self.settled_at.isoformat() if self.settled_at else None,
            "batch_id": str(self.batch_id) if self.batch_id else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class SettlementBatch(Base):
    """结算批次 — 按周期汇总的结算记录

    status 枚举：
    - draft     : 草稿（系统生成，待确认）
    - confirmed : 已确认（财务审核通过）
    - paid      : 已付款（资金已划转）
    """

    __tablename__ = "settlement_batches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    batch_no: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True, comment="批次编号，格式: SB{YYYYMMDD}{SEQ}"
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False, comment="结算周期起始日期")
    period_end: Mapped[date] = mapped_column(Date, nullable=False, comment="结算周期截止日期")
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    total_orders: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="订单总数")
    total_amount_fen: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="订单总金额（分）")
    total_split_fen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="总分账金额（分）= platform_fee + brand_royalty"
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", comment="状态: draft/confirmed/paid"
    )

    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_settlement_batches_tenant_store", "tenant_id", "store_id"),
        Index("ix_settlement_batches_tenant_status", "tenant_id", "status"),
        Index("ix_settlement_batches_batch_no", "tenant_id", "batch_no"),
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "batch_no": self.batch_no,
            "period_start": str(self.period_start),
            "period_end": str(self.period_end),
            "store_id": str(self.store_id),
            "total_orders": self.total_orders,
            "total_amount_fen": self.total_amount_fen,
            "total_split_fen": self.total_split_fen,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
