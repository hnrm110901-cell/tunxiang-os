"""v107: 储值账户与交易明细表

新建 2 张表：
  stored_value_accounts     — 每个会员的储值账户（余额、冻结、累计充/消）
  stored_value_transactions — 充值/消费/退款/调整/过期流水明细

设计要点：
  - 金额全部以"分"为单位存储，规避浮点精度问题
  - amount_fen 正值=入账，负值=出账
  - type CHECK: recharge/consume/refund/adjustment/expire
  - payment_method CHECK: cash/wechat/alipay/card
  - RLS: NULLIF(app.tenant_id) 防 NULL 绕过
  - 索引覆盖 tenant_id / member_id / account_id / created_at

Revision ID: v107
Revises: v106
Create Date: 2026-04-02
"""

from alembic import op

revision = "v107"
down_revision = "v106"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. 储值账户表 ──────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS stored_value_accounts (
            id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id            UUID        NOT NULL,
            member_id            UUID        NOT NULL,
            balance_fen          BIGINT      NOT NULL DEFAULT 0,
            frozen_fen           BIGINT      NOT NULL DEFAULT 0,
            total_recharged_fen  BIGINT      NOT NULL DEFAULT 0,
            total_consumed_fen   BIGINT      NOT NULL DEFAULT 0,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted           BOOLEAN     NOT NULL DEFAULT FALSE,
            CONSTRAINT stored_value_accounts_balance_nonneg
                CHECK (balance_fen >= 0),
            CONSTRAINT stored_value_accounts_frozen_nonneg
                CHECK (frozen_fen >= 0)
        )
    """)
    op.execute("ALTER TABLE stored_value_accounts ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY stored_value_accounts_tenant_isolation ON stored_value_accounts
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_stored_value_accounts_member
            ON stored_value_accounts(tenant_id, member_id)
            WHERE is_deleted = FALSE
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_stored_value_accounts_tenant
            ON stored_value_accounts(tenant_id)
    """)

    # ── 2. 交易流水表 ──────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS stored_value_transactions (
            id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id            UUID        NOT NULL,
            account_id           UUID        NOT NULL REFERENCES stored_value_accounts(id),
            member_id            UUID        NOT NULL,
            order_id             UUID,
            type                 TEXT        NOT NULL
                                     CHECK (type IN ('recharge','consume','refund','adjustment','expire')),
            amount_fen           BIGINT      NOT NULL,
            balance_before_fen   BIGINT,
            balance_after_fen    BIGINT,
            operator_id          VARCHAR(64),
            note                 TEXT,
            payment_method       VARCHAR(32)
                                     CHECK (payment_method IN ('cash','wechat','alipay','card') OR payment_method IS NULL),
            external_payment_id  VARCHAR(128),
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("ALTER TABLE stored_value_transactions ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY stored_value_transactions_tenant_isolation ON stored_value_transactions
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sv_txn_account
            ON stored_value_transactions(account_id, created_at DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sv_txn_member
            ON stored_value_transactions(tenant_id, member_id, created_at DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sv_txn_tenant
            ON stored_value_transactions(tenant_id)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS stored_value_transactions CASCADE")
    op.execute("DROP TABLE IF EXISTS stored_value_accounts CASCADE")
