"""储值账户模型 — 基于账户维度（区别于 stored_value.py 的卡维度）

本模块实现以账户为中心的储值体系，支持：
- 余额 / 赠送余额分开核销
- 状态：active / frozen / expired
- 完整流水记录（balance_before / balance_after）

# SCHEMA SQL:
#
# CREATE TABLE stored_value_accounts (
#     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#     tenant_id UUID NOT NULL,
#     member_id UUID NOT NULL REFERENCES members(id),
#     balance NUMERIC(10,2) NOT NULL DEFAULT 0,
#     gift_balance NUMERIC(10,2) DEFAULT 0,    -- 赠送余额（可分开核销）
#     total_recharged NUMERIC(12,2) DEFAULT 0,
#     total_consumed NUMERIC(12,2) DEFAULT 0,
#     status VARCHAR(20) DEFAULT 'active',      -- active/frozen/expired
#     expired_at TIMESTAMPTZ,
#     created_at TIMESTAMPTZ DEFAULT NOW(),
#     updated_at TIMESTAMPTZ DEFAULT NOW()
# );
#
# -- RLS (使用 v006+ safe pattern)
# ALTER TABLE stored_value_accounts ENABLE ROW LEVEL SECURITY;
# ALTER TABLE stored_value_accounts FORCE ROW LEVEL SECURITY;
# CREATE POLICY stored_value_accounts_rls_select ON stored_value_accounts
#     FOR SELECT USING (
#         current_setting('app.tenant_id', TRUE) IS NOT NULL
#         AND current_setting('app.tenant_id', TRUE) <> ''
#         AND tenant_id = current_setting('app.tenant_id')::UUID
#     );
# -- (同理创建 insert/update/delete 策略)
#
# CREATE TABLE stored_value_account_transactions (
#     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#     tenant_id UUID NOT NULL,
#     account_id UUID NOT NULL REFERENCES stored_value_accounts(id),
#     transaction_type VARCHAR(20) NOT NULL,   -- recharge/consume/refund/transfer_in/transfer_out/gift
#     amount NUMERIC(10,2) NOT NULL,
#     balance_before NUMERIC(10,2) NOT NULL,
#     balance_after NUMERIC(10,2) NOT NULL,
#     order_id UUID,
#     remark TEXT,
#     operator_id UUID,
#     created_at TIMESTAMPTZ DEFAULT NOW()
# );
#
# -- 索引
# CREATE UNIQUE INDEX idx_sva_member_tenant ON stored_value_accounts(member_id, tenant_id);
# CREATE INDEX idx_svat_account_id ON stored_value_account_transactions(account_id, created_at DESC);
# CREATE INDEX idx_svat_order_id ON stored_value_account_transactions(order_id) WHERE order_id IS NOT NULL;
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class StoredValueAccount(TenantBase):
    """储值账户主表（以账户/会员为维度）

    与 StoredValueCard 的区别：
    - StoredValueCard 以"卡号"为维度（支持实体卡、匿名卡）
    - StoredValueAccount 以"会员账户"为维度（一个会员一个账户）
    """
    __tablename__ = "stored_value_accounts"

    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
        comment="关联会员 ID",
    )

    # 余额（元，Numeric 精度避免浮点误差）
    balance: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False, default=0,
        comment="本金余额（元）",
    )
    gift_balance: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False, default=0,
        comment="赠送余额（元），可分开核销",
    )

    # 累计统计
    total_recharged: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, default=0,
        comment="累计充值金额（元）",
    )
    total_consumed: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, default=0,
        comment="累计消费金额（元）",
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active",
        comment="账户状态：active | frozen | expired",
    )
    expired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="账户到期时间，NULL=永不过期",
    )

    __table_args__ = (
        UniqueConstraint("member_id", "tenant_id", name="uq_sva_member_tenant"),
        {"comment": "储值账户主表"},
    )


class StoredValueAccountTransaction(TenantBase):
    """储值账户流水（以账户为维度）

    记录每笔操作的 balance_before / balance_after，满足对账需求。
    """
    __tablename__ = "stored_value_account_transactions"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
        comment="关联储值账户 ID",
    )
    transaction_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="recharge | consume | refund | transfer_in | transfer_out | gift",
    )

    # 金额字段（元）
    amount: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False,
        comment="变动金额（正=增加，负=减少，元）",
    )
    gift_amount: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False, default=0,
        comment="赠送余额变动（元）",
    )

    # 流水快照（用于对账）
    balance_before: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False,
        comment="操作前本金余额快照（元）",
    )
    balance_after: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False,
        comment="操作后本金余额快照（元）",
    )
    gift_balance_before: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False, default=0,
        comment="操作前赠送余额快照（元）",
    )
    gift_balance_after: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False, default=0,
        comment="操作后赠送余额快照（元）",
    )

    # 关联业务
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
        comment="关联订单 ID（消费时填写）",
    )
    operator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
        comment="操作员 ID",
    )
    remark: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
        comment="备注",
    )

    __table_args__ = (
        Index("idx_svat_account_created", "account_id", "created_at"),
        Index("idx_svat_order_id", "order_id"),
        {"comment": "储值账户流水表"},
    )
