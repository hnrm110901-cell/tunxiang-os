"""v155 — 加盟费用收缴表

新增一张表：
  franchise_fees  — 加盟费用账单（特许权费/管理费/品牌使用费/培训费）

RLS 策略：NULLIF(current_setting('app.tenant_id', true), '')::uuid 标准安全模式。

Revision ID: v155
Revises: v154
Create Date: 2026-04-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "v155"
down_revision= "v154"
branch_labels= None
depends_on= None

_SAFE_CONDITION = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # ── franchise_fees 加盟费用 ──────────────────────────────────
    if "franchise_fees" not in _existing:
        op.create_table(
            "franchise_fees",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("franchisee_id", UUID(as_uuid=True), nullable=False),
            sa.Column("fee_type", sa.String(50), nullable=False,
                      comment="royalty/management/brand/training"),
            sa.Column("amount_fen", sa.BigInteger, nullable=False,
                      server_default="0"),
            sa.Column("due_date", sa.Date),
            sa.Column("paid_date", sa.Date),
            sa.Column("status", sa.String(20), nullable=False,
                      server_default="pending",
                      comment="pending/paid/overdue"),
            sa.Column("notes", sa.Text),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False,
                      server_default="false"),
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_franchise_fees_tenant "
        "ON franchise_fees (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_franchise_fees_franchisee "
        "ON franchise_fees (tenant_id, franchisee_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_franchise_fees_status "
        "ON franchise_fees (tenant_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_franchise_fees_due_date "
        "ON franchise_fees (tenant_id, due_date)"
    )

    # RLS
    op.execute("ALTER TABLE franchise_fees ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE franchise_fees FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY franchise_fees_rls_select ON franchise_fees "
        f"FOR SELECT USING ({_SAFE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY franchise_fees_rls_insert ON franchise_fees "
        f"FOR INSERT WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY franchise_fees_rls_update ON franchise_fees "
        f"FOR UPDATE USING ({_SAFE_CONDITION}) WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY franchise_fees_rls_delete ON franchise_fees "
        f"FOR DELETE USING ({_SAFE_CONDITION})"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS franchise_fees_rls_delete ON franchise_fees")
    op.execute("DROP POLICY IF EXISTS franchise_fees_rls_update ON franchise_fees")
    op.execute("DROP POLICY IF EXISTS franchise_fees_rls_insert ON franchise_fees")
    op.execute("DROP POLICY IF EXISTS franchise_fees_rls_select ON franchise_fees")
    op.drop_table("franchise_fees")
