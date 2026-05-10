"""储值账户模型 — 基于账户维度（区别于 stored_value.py 的卡维度）

本模块实现以账户为中心的储值体系，支持：
- 余额 / 赠送余额分开核销
- 状态：active / frozen / expired

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
# -- 索引
# CREATE UNIQUE INDEX idx_sva_member_tenant ON stored_value_accounts(member_id, tenant_id);

注：原同模块 StoredValueAccountTransaction 流水类移除 — ORM 文档化但从未做成
alembic migration（main chain 无 CREATE TABLE），0 外部引用。真实 stored_value
流水由 stored_value.py / 其他模块负责。audit 详见 docs/orm-drift-class-c-audit.md。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Numeric, String, UniqueConstraint
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
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="关联会员 ID",
    )

    # 余额（元，Numeric 精度避免浮点误差）
    balance: Mapped[float] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=0,
        comment="本金余额（元）",
    )
    gift_balance: Mapped[float] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=0,
        comment="赠送余额（元），可分开核销",
    )

    # 累计统计
    total_recharged: Mapped[float] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=0,
        comment="累计充值金额（元）",
    )
    total_consumed: Mapped[float] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=0,
        comment="累计消费金额（元）",
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        comment="账户状态：active | frozen | expired",
    )
    expired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="账户到期时间，NULL=永不过期",
    )

    __table_args__ = (
        UniqueConstraint("member_id", "tenant_id", name="uq_sva_member_tenant"),
        {"comment": "储值账户主表"},
    )
