"""v152 — 邀请码系统 + 发票管理

新增四张表：
  invite_codes      — 会员邀请码（每人唯一，含使用次数统计）
  invite_records    — 邀请关系记录（被邀请人、状态、积分发放）
  invoice_titles    — 发票抬头（个人/企业）
  invoices          — 发票申请记录

RLS 策略：NULLIF(current_setting('app.tenant_id', true), '')::uuid 模式。

Revision ID: v152
Revises: v151
Create Date: 2026-04-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "v152"
down_revision= "v151"
branch_labels= None
depends_on= None


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # ── 1. invite_codes 邀请码主表 ────────────────────────────────
    if "invite_codes" not in _existing:
        op.create_table(
            "invite_codes",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("member_id", UUID(as_uuid=True), nullable=False),
            sa.Column("code", sa.String(20), nullable=False),
            sa.Column("invited_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("total_points_earned", sa.Integer, nullable=False, server_default="0"),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='invite_codes' AND column_name IN ('tenant_id', 'member_id')) = 2 THEN
                EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS ix_invite_codes_tenant_member ON invite_codes (tenant_id, member_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='invite_codes' AND (column_name = 'code')) = 1 THEN
                EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS ix_invite_codes_code ON invite_codes (code)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE invite_codes ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS invite_codes_tenant_isolation ON invite_codes;")
    op.execute("DROP POLICY IF EXISTS invite_codes_tenant_isolation ON invite_codes;")
    op.execute("""
        CREATE POLICY invite_codes_tenant_isolation ON invite_codes
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        );
    """)

    # ── 2. invite_records 邀请关系记录 ────────────────────────────
    if "invite_records" not in _existing:
        op.create_table(
            "invite_records",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("invite_code_id", UUID(as_uuid=True), nullable=False),
            sa.Column("inviter_member_id", UUID(as_uuid=True), nullable=False),
            sa.Column("invitee_member_id", UUID(as_uuid=True), nullable=False),
            sa.Column("invite_code", sa.String(20), nullable=False),
            sa.Column(
                "status", sa.String(20), nullable=False, server_default="pending",
            ),
            sa.Column("inviter_points", sa.Integer, nullable=False, server_default="0"),
            sa.Column("invitee_points", sa.Integer, nullable=False, server_default="0"),
            sa.Column("first_order_id", UUID(as_uuid=True), nullable=True),
            sa.Column("credited_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='invite_records' AND column_name IN ('tenant_id', 'inviter_member_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_invite_records_tenant_inviter ON invite_records (tenant_id, inviter_member_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='invite_records' AND column_name IN ('tenant_id', 'invitee_member_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_invite_records_invitee ON invite_records (tenant_id, invitee_member_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='invite_records' AND (column_name = 'invite_code')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_invite_records_code ON invite_records (invite_code)';
            END IF;
        END $$;
    """)
    # 防止同一被邀请人多次使用邀请码
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='invite_records' AND column_name IN ('tenant_id', 'invitee_member_id')) = 2 THEN
                EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS uq_invite_records_invitee ON invite_records (tenant_id, invitee_member_id)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE invite_records ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS invite_records_tenant_isolation ON invite_records;")
    op.execute("DROP POLICY IF EXISTS invite_records_tenant_isolation ON invite_records;")
    op.execute("""
        CREATE POLICY invite_records_tenant_isolation ON invite_records
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        );
    """)

    # ── 3. invoice_titles 发票抬头 ────────────────────────────────
    if "invoice_titles" not in _existing:
        op.create_table(
            "invoice_titles",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
            sa.Column("type", sa.String(20), nullable=False, server_default="personal"),
            sa.Column("title", sa.String(100), nullable=False, server_default=""),
            sa.Column("tax_id", sa.String(50), nullable=False, server_default=""),
            sa.Column("address", sa.String(200), nullable=False, server_default=""),
            sa.Column("phone", sa.String(30), nullable=False, server_default=""),
            sa.Column("bank_name", sa.String(100), nullable=False, server_default=""),
            sa.Column("bank_account", sa.String(50), nullable=False, server_default=""),
            sa.Column("is_default", sa.Boolean, nullable=False, server_default="false"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='invoice_titles' AND column_name IN ('tenant_id', 'customer_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_invoice_titles_tenant_customer ON invoice_titles (tenant_id, customer_id)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE invoice_titles ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS invoice_titles_tenant_isolation ON invoice_titles;")
    op.execute("DROP POLICY IF EXISTS invoice_titles_tenant_isolation ON invoice_titles;")
    op.execute("""
        CREATE POLICY invoice_titles_tenant_isolation ON invoice_titles
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        );
    """)

    # ── 4. invoices 发票申请记录 ──────────────────────────────────
    if "invoices" not in _existing:
        op.create_table(
        "invoices",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=True),
        sa.Column("order_id", UUID(as_uuid=True), nullable=True),
        sa.Column("order_no", sa.String(50), nullable=False, server_default=""),
        sa.Column("amount_fen", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("invoice_title_id", UUID(as_uuid=True), nullable=True),
        sa.Column("title_snapshot", sa.String(100), nullable=False, server_default=""),
        sa.Column("type_snapshot", sa.String(20), nullable=False, server_default="personal"),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="pending",
        ),
        sa.Column("invoice_no", sa.String(50), nullable=True),
        sa.Column("issued_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='invoices' AND column_name IN ('tenant_id', 'customer_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_invoices_tenant_customer ON invoices (tenant_id, customer_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='invoices' AND column_name IN ('tenant_id', 'status')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_invoices_tenant_status ON invoices (tenant_id, status)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='invoices' AND (column_name = 'created_at')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_invoices_created_at ON invoices (created_at)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS invoices_tenant_isolation ON invoices;")
    op.execute("DROP POLICY IF EXISTS invoices_tenant_isolation ON invoices;")
    op.execute("""
        CREATE POLICY invoices_tenant_isolation ON invoices
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        );
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS invoices_tenant_isolation ON invoices;")
    op.drop_table("invoices")
    op.execute("DROP POLICY IF EXISTS invoice_titles_tenant_isolation ON invoice_titles;")
    op.drop_table("invoice_titles")
    op.execute("DROP POLICY IF EXISTS invite_records_tenant_isolation ON invite_records;")
    op.drop_table("invite_records")
    op.execute("DROP POLICY IF EXISTS invite_codes_tenant_isolation ON invite_codes;")
    op.drop_table("invite_codes")
