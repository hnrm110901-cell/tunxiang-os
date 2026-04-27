"""v249: banquet KDS dishes + session deposits tables

Revision ID: v249
Revises: v248
Create Date: 2026-04-13

Fix: schema aligned with banquet_kds_routes.py and banquet_deposit_routes.py
  - banquet_kds_dishes:  total_qty/served_qty/serve_status/sequence_no/is_deleted/notes
  - banquet_session_deposits: balance_fen/collected_at/applied_at + status default 'active'
"""

from alembic import op

revision = "v249"
down_revision = "v248"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # banquet_kds_dishes — 宴会场次出品明细（懒加载初始化）
    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_kds_dishes (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            session_id      UUID NOT NULL,
            dish_id         UUID NOT NULL,
            dish_name       VARCHAR(128) NOT NULL,
            total_qty       INTEGER NOT NULL DEFAULT 1,
            served_qty      INTEGER NOT NULL DEFAULT 0,
            serve_status    VARCHAR(32) NOT NULL DEFAULT 'pending',
            sequence_no     INTEGER NOT NULL DEFAULT 0,
            is_deleted      BOOLEAN NOT NULL DEFAULT FALSE,
            called_at       TIMESTAMPTZ,
            served_at       TIMESTAMPTZ,
            operator_id     UUID,
            notes           TEXT,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_banquet_kds_dishes_session
            ON banquet_kds_dishes (tenant_id, session_id)
    """)
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE banquet_kds_dishes ENABLE ROW LEVEL SECURITY;
        EXCEPTION WHEN others THEN NULL; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE POLICY banquet_kds_dishes_rls ON banquet_kds_dishes
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """)

    # banquet_session_deposits — 宴会场次定金台账
    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_session_deposits (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            session_id      UUID NOT NULL,
            amount_fen      INTEGER NOT NULL,
            balance_fen     INTEGER NOT NULL,
            status          VARCHAR(32) NOT NULL DEFAULT 'active',
            collected_at    TIMESTAMPTZ DEFAULT NOW(),
            applied_at      TIMESTAMPTZ,
            refunded_at     TIMESTAMPTZ,
            payment_method  VARCHAR(32) DEFAULT 'cash',
            operator_id     UUID,
            notes           TEXT,
            metadata        JSONB DEFAULT '{}',
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT chk_deposit_amount_positive CHECK (amount_fen > 0),
            CONSTRAINT chk_deposit_balance_nonneg CHECK (balance_fen >= 0)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_banquet_deposits_session
            ON banquet_session_deposits (tenant_id, session_id)
    """)
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE banquet_session_deposits ENABLE ROW LEVEL SECURITY;
        EXCEPTION WHEN others THEN NULL; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE POLICY banquet_session_deposits_rls ON banquet_session_deposits
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS banquet_session_deposits")
    op.execute("DROP TABLE IF EXISTS banquet_kds_dishes")
