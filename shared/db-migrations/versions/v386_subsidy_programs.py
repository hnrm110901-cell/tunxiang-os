"""v386 — 马来西亚政府补贴方案相关表

新增两张表支持 Phase 2 Sprint 2.5 Malaysia 政府补贴计费：

1. tenant_subsidies — 商户补贴申请记录
   - 记录每个商户已申请的补贴方案、补贴率、有效期
   - 支持 MDEC Digitalisation Grant / SME Corp Automasuk

2. subsidy_bills — 补贴后账单
   - 记录每期补贴账单，base_fee - subsidy = payable
   - 跟踪支付状态（pending/paid/overdue/cancelled）

RLS 策略：
  - INSERT: tenant_id = current_app_tenant()
  - SELECT/UPDATE/DELETE: tenant_id = current_app_tenant()
  - 强制租户隔离

Revision ID: v386
Revises: v385
Create Date: 2026-05-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v386"
down_revision: Union[str, Sequence[str], None] = "v385"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── tenant_subsidies 表 ──────────────────────────────────
    op.create_table(
        "tenant_subsidies",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("program", sa.VARCHAR(50), nullable=False, comment="补贴方案ID: mdec_digital_grant / smecorp_automasuk"),
        sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="active", comment="active / expired / cancelled"),
        sa.Column("subsidy_rate", sa.DECIMAL(3, 2), nullable=False, comment="政府补贴率，如 0.50 表示50%"),
        sa.Column("monthly_fee_fen", sa.Integer, nullable=False, comment="月基础费（分），如 3500 = RM35"),
        sa.Column("subsidy_amount_fen", sa.Integer, nullable=False, comment="月补贴金额（分）"),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, comment="补贴有效期截止日"),
        sa.Column("country_code", sa.VARCHAR(10), nullable=False, server_default="MY", comment="国家代码"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
        sa.UniqueConstraint("tenant_id", "program", name="uq_tenant_subsidy_program"),
        comment="商户补贴申请记录",
    )

    op.create_index("idx_subsidies_tenant_status", "tenant_subsidies", ["tenant_id", "status"])
    op.create_index("idx_subsidies_expires", "tenant_subsidies", ["expires_at"])

    # ── subsidy_bills 表 ─────────────────────────────────────
    op.create_table(
        "subsidy_bills",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "subsidy_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("tenant_subsidies.id", ondelete="SET NULL"),
            nullable=True,
            comment="关联补贴记录（可为NULL表示非补贴周期）",
        ),
        sa.Column("period_start", sa.Date, nullable=False, comment="账单周期起始日"),
        sa.Column("period_end", sa.Date, nullable=False, comment="账单周期结束日"),
        sa.Column("base_fee_fen", sa.Integer, nullable=False, comment="补贴前基础费用（分）"),
        sa.Column("subsidy_fen", sa.Integer, nullable=False, default=0, comment="补贴抵扣金额（分）"),
        sa.Column("payable_fen", sa.Integer, nullable=False, comment="应付金额（分）= base_fee_fen - subsidy_fen"),
        sa.Column(
            "status",
            sa.VARCHAR(20),
            nullable=False,
            server_default="pending",
            comment="pending / paid / overdue / cancelled",
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True, comment="支付完成时间"),
        sa.Column("country_code", sa.VARCHAR(10), nullable=False, server_default="MY", comment="国家代码"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
        comment="补贴后账单记录",
    )

    op.create_index("idx_subsidy_bills_tenant_status", "subsidy_bills", ["tenant_id", "status"])
    op.create_index("idx_subsidy_bills_period", "subsidy_bills", ["tenant_id", "period_start", "period_end"])

    # ── RLS 策略 ─────────────────────────────────────────────
    # tenant_subsidies RLS
    op.execute("ALTER TABLE tenant_subsidies ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_subsidies_insert ON tenant_subsidies
            FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid)
    """)
    op.execute("""
        CREATE POLICY tenant_subsidies_select ON tenant_subsidies
            FOR SELECT USING (tenant_id = current_setting('app.tenant_id')::uuid)
    """)
    op.execute("""
        CREATE POLICY tenant_subsidies_update ON tenant_subsidies
            FOR UPDATE USING (tenant_id = current_setting('app.tenant_id')::uuid)
    """)
    op.execute("""
        CREATE POLICY tenant_subsidies_delete ON tenant_subsidies
            FOR DELETE USING (tenant_id = current_setting('app.tenant_id')::uuid)
    """)

    # subsidy_bills RLS
    op.execute("ALTER TABLE subsidy_bills ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY subsidy_bills_insert ON subsidy_bills
            FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid)
    """)
    op.execute("""
        CREATE POLICY subsidy_bills_select ON subsidy_bills
            FOR SELECT USING (tenant_id = current_setting('app.tenant_id')::uuid)
    """)
    op.execute("""
        CREATE POLICY subsidy_bills_update ON subsidy_bills
            FOR UPDATE USING (tenant_id = current_setting('app.tenant_id')::uuid)
    """)
    op.execute("""
        CREATE POLICY subsidy_bills_delete ON subsidy_bills
            FOR DELETE USING (tenant_id = current_setting('app.tenant_id')::uuid)
    """)


def downgrade() -> None:
    # 删除 RLS 策略
    op.execute("DROP POLICY IF EXISTS tenant_subsidies_insert ON tenant_subsidies")
    op.execute("DROP POLICY IF EXISTS tenant_subsidies_select ON tenant_subsidies")
    op.execute("DROP POLICY IF EXISTS tenant_subsidies_update ON tenant_subsidies")
    op.execute("DROP POLICY IF EXISTS tenant_subsidies_delete ON tenant_subsidies")
    op.execute("ALTER TABLE tenant_subsidies DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS subsidy_bills_insert ON subsidy_bills")
    op.execute("DROP POLICY IF EXISTS subsidy_bills_select ON subsidy_bills")
    op.execute("DROP POLICY IF EXISTS subsidy_bills_update ON subsidy_bills")
    op.execute("DROP POLICY IF EXISTS subsidy_bills_delete ON subsidy_bills")
    op.execute("ALTER TABLE subsidy_bills DISABLE ROW LEVEL SECURITY")

    # 删除表
    op.drop_table("subsidy_bills")
    op.drop_table("tenant_subsidies")
