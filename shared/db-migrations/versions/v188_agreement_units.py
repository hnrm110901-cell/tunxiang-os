"""协议单位体系 — 企业挂账/预付管理

Revision ID: v188
Revises: v187
Create Date: 2026-04-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "v188"
down_revision = "v187b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── 1. agreement_units — 协议单位档案 ────────────────────────────────────
    op.create_table(
        "agreement_units",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.VARCHAR(100), nullable=False),
        sa.Column("short_name", sa.VARCHAR(50), nullable=True),
        sa.Column("contact_name", sa.VARCHAR(50), nullable=True),
        sa.Column("contact_phone", sa.VARCHAR(20), nullable=True),
        sa.Column("credit_limit_fen", sa.BIGINT(), nullable=False, server_default="0"),
        sa.Column("settlement_cycle", sa.VARCHAR(20), nullable=True, comment="monthly/weekly/custom"),
        sa.Column("settlement_day", sa.Integer(), nullable=True, comment="月结算日，如15=每月15号"),
        sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="active", comment="active/suspended/closed"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_index("idx_agreement_units_tenant_id", "agreement_units", ["tenant_id"])
    op.create_index("idx_agreement_units_status", "agreement_units", ["tenant_id", "status"])

    # ─── 2. agreement_accounts — 账户余额 ────────────────────────────────────
    op.create_table(
        "agreement_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "balance_fen", sa.BIGINT(), nullable=False, server_default="0", comment="当前余额（分），可为负=已欠款"
        ),
        sa.Column("credit_used_fen", sa.BIGINT(), nullable=False, server_default="0", comment="已用授信额度"),
        sa.Column("total_consumed_fen", sa.BIGINT(), nullable=False, server_default="0", comment="累计消费"),
        sa.Column("total_repaid_fen", sa.BIGINT(), nullable=False, server_default="0", comment="累计还款"),
        sa.Column("last_transaction_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["unit_id"], ["agreement_units.id"], ondelete="RESTRICT"),
    )
    op.create_index("idx_agreement_accounts_tenant_id", "agreement_accounts", ["tenant_id"])
    op.create_index("idx_agreement_accounts_unit_id", "agreement_accounts", ["unit_id"])

    # ─── 3. prepaid_records — 预付充值/退款记录 ──────────────────────────────
    op.create_table(
        "prepaid_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("type", sa.VARCHAR(20), nullable=False, comment="recharge/refund"),
        sa.Column("amount_fen", sa.BIGINT(), nullable=False),
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["unit_id"], ["agreement_units.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["account_id"], ["agreement_accounts.id"], ondelete="SET NULL"),
    )
    op.create_index("idx_prepaid_records_tenant_id", "prepaid_records", ["tenant_id"])
    op.create_index("idx_prepaid_records_unit_id", "prepaid_records", ["unit_id"])
    op.create_index("idx_prepaid_records_created_at", "prepaid_records", ["tenant_id", "created_at"])

    # ─── 4. agreement_transactions — 挂账/还款流水 ───────────────────────────
    op.create_table(
        "agreement_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("type", sa.VARCHAR(20), nullable=False, comment="charge/repay/manual_charge"),
        sa.Column("amount_fen", sa.BIGINT(), nullable=False, comment="挂账为正，还款为负"),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True, comment="挂账时关联订单"),
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("repay_method", sa.VARCHAR(30), nullable=True, comment="cash/transfer/wechat"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_index("idx_agreement_transactions_tenant_id", "agreement_transactions", ["tenant_id"])
    op.create_index("idx_agreement_transactions_unit_id", "agreement_transactions", ["unit_id"])
    op.create_index("idx_agreement_transactions_created_at", "agreement_transactions", ["tenant_id", "created_at"])
    op.create_index(
        "idx_agreement_transactions_order_id",
        "agreement_transactions",
        ["order_id"],
        postgresql_where=sa.text("order_id IS NOT NULL"),
    )

    # ─── RLS 策略（4张表） ────────────────────────────────────────────────────
    for table in ("agreement_units", "agreement_accounts", "prepaid_records", "agreement_transactions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
            USING (tenant_id = (current_setting('app.tenant_id', true)::UUID))
        """)


def downgrade() -> None:
    for table in ("agreement_units", "agreement_accounts", "prepaid_records", "agreement_transactions"):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")

    op.drop_table("agreement_transactions")
    op.drop_table("prepaid_records")
    op.drop_table("agreement_accounts")
    op.drop_table("agreement_units")
