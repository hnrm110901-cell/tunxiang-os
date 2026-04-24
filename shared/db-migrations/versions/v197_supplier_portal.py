"""供应商门户持久化保障 — 去除静默内存降级

Revision ID: v197
Revises: v196
Create Date: 2026-04-07
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "v197"
down_revision = "v196"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── 1. supplier_profiles 补充字段 ────────────────────────────────────────
    # 检查并补充门户登录/状态/收款/税务/联系/评级/统计字段
    op.execute("""
        ALTER TABLE supplier_accounts
            ADD COLUMN IF NOT EXISTS portal_password_hash VARCHAR(255),
            ADD COLUMN IF NOT EXISTS portal_last_login TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS portal_status VARCHAR(20) NOT NULL DEFAULT 'active',
            ADD COLUMN IF NOT EXISTS bank_account VARCHAR(50),
            ADD COLUMN IF NOT EXISTS bank_name VARCHAR(100),
            ADD COLUMN IF NOT EXISTS tax_no VARCHAR(30),
            ADD COLUMN IF NOT EXISTS contact_email VARCHAR(100),
            ADD COLUMN IF NOT EXISTS rating NUMERIC(3,2) NOT NULL DEFAULT 5.0,
            ADD COLUMN IF NOT EXISTS total_orders INT NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS total_amount_fen BIGINT NOT NULL DEFAULT 0
    """)

    # ─── 2. supplier_rfq_requests — 询价单（RFQ） ─────────────────────────────
    op.create_table(
        "supplier_rfq_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_no", sa.VARCHAR(30), unique=True, nullable=True, comment="询价单号：RFQ-YYYYMM-XXXX"),
        sa.Column(
            "status",
            sa.VARCHAR(20),
            nullable=False,
            server_default="pending",
            comment="pending/quoted/accepted/rejected/expired",
        ),
        sa.Column(
            "items",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
            comment="询价品目：[{ingredient_id, name, qty, unit}]",
        ),
        sa.Column("expected_delivery_date", sa.Date(), nullable=True),
        sa.Column("quote_valid_until", sa.Date(), nullable=True),
        sa.Column("quoted_price_fen", sa.BigInteger(), nullable=True, comment="供应商报价，单位：分"),
        sa.Column("accepted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )

    # 索引
    op.create_index("idx_supplier_rfq_tenant", "supplier_rfq_requests", ["tenant_id"])
    op.create_index("idx_supplier_rfq_supplier", "supplier_rfq_requests", ["tenant_id", "supplier_id"])
    op.create_index("idx_supplier_rfq_status", "supplier_rfq_requests", ["tenant_id", "status"])
    op.create_index(
        "idx_supplier_rfq_request_no",
        "supplier_rfq_requests",
        ["request_no"],
        postgresql_where=sa.text("request_no IS NOT NULL"),
    )

    # ─── 3. RLS 策略 ─────────────────────────────────────────────────────────
    op.execute("ALTER TABLE supplier_rfq_requests ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY supplier_rfq_requests_tenant_isolation ON supplier_rfq_requests
        USING (tenant_id = (current_setting('app.tenant_id', true)::UUID))
    """)

    # supplier_accounts RLS（仅在未存在时创建）
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'supplier_accounts'
                  AND policyname = 'supplier_accounts_tenant_isolation'
            ) THEN
                ALTER TABLE supplier_accounts ENABLE ROW LEVEL SECURITY;
                CREATE POLICY supplier_accounts_tenant_isolation ON supplier_accounts
                USING (tenant_id = (current_setting('app.tenant_id', true)::UUID));
            END IF;
        END
        $$
    """)


def downgrade() -> None:
    # 删除 RLS 策略
    op.execute("DROP POLICY IF EXISTS supplier_rfq_requests_tenant_isolation ON supplier_rfq_requests")

    # 删除 supplier_rfq_requests 表
    op.drop_table("supplier_rfq_requests")

    # 回滚 supplier_accounts 新增字段
    op.execute("""
        ALTER TABLE supplier_accounts
            DROP COLUMN IF EXISTS portal_password_hash,
            DROP COLUMN IF EXISTS portal_last_login,
            DROP COLUMN IF EXISTS portal_status,
            DROP COLUMN IF EXISTS bank_account,
            DROP COLUMN IF EXISTS bank_name,
            DROP COLUMN IF EXISTS tax_no,
            DROP COLUMN IF EXISTS contact_email,
            DROP COLUMN IF EXISTS rating,
            DROP COLUMN IF EXISTS total_orders,
            DROP COLUMN IF EXISTS total_amount_fen
    """)
