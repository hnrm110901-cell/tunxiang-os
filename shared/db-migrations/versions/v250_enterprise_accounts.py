"""v250 企业挂账账户表

新增：
  enterprise_accounts      — 企业客户档案 + 授信额度
  enterprise_sign_records  — 签单记录（按订单）

审计背景：enterprise_account.py 原使用内存dict存储，
多进程部署时 authorize_sign 存在竞态风险（check_credit→扣额度无锁）。
此迁移将数据持久化到DB，并通过原子SQL消除竞态。
"""

from alembic import op

revision = "v250"
down_revision = "v249"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── enterprise_accounts ────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS enterprise_accounts (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID        NOT NULL,
            name                VARCHAR(200) NOT NULL,
            contact             VARCHAR(200),
            credit_limit_fen    BIGINT      NOT NULL DEFAULT 0
                                CHECK (credit_limit_fen >= 0),
            used_fen            BIGINT      NOT NULL DEFAULT 0
                                CHECK (used_fen >= 0),
            billing_cycle       VARCHAR(20) NOT NULL DEFAULT 'monthly',
            status              VARCHAR(20) NOT NULL DEFAULT 'active',
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN     NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_enterprise_accounts_tenant_name
            ON enterprise_accounts(tenant_id, name)
            WHERE is_deleted = FALSE
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_enterprise_accounts_tenant
            ON enterprise_accounts(tenant_id)
    """)
    op.execute("ALTER TABLE enterprise_accounts ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY enterprise_accounts_tenant_isolation
            ON enterprise_accounts
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)

    # ── enterprise_sign_records ────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS enterprise_sign_records (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID        NOT NULL,
            enterprise_id       UUID        NOT NULL REFERENCES enterprise_accounts(id),
            order_id            UUID        NOT NULL,
            signer_name         VARCHAR(100) NOT NULL,
            amount_fen          BIGINT      NOT NULL CHECK (amount_fen > 0),
            status              VARCHAR(20) NOT NULL DEFAULT 'pending',
            settled_at          TIMESTAMPTZ,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_enterprise_sign_records_order
            ON enterprise_sign_records(tenant_id, order_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_enterprise_sign_records_enterprise
            ON enterprise_sign_records(enterprise_id)
    """)
    op.execute("ALTER TABLE enterprise_sign_records ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY enterprise_sign_records_tenant_isolation
            ON enterprise_sign_records
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS enterprise_sign_records CASCADE")
    op.execute("DROP TABLE IF EXISTS enterprise_accounts CASCADE")
