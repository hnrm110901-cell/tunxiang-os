"""v168: 扫码支付流水表 — scan_pay_transactions

字段：
  id UUID PK, tenant_id UUID(RLS), store_id UUID,
  payment_id VARCHAR(50) NOT NULL UNIQUE,  -- 系统内部 ID（如 SPY-xxxx）
  auth_code VARCHAR(100) NOT NULL,         -- 顾客付款码
  channel VARCHAR(20) CHECK('wechat','alipay','unionpay'),
  amount_fen BIGINT NOT NULL,
  status VARCHAR(20) CHECK('pending','paid','failed','cancelled'),
  cashier_id VARCHAR(100),                 -- 收银员 ID
  merchant_order_id VARCHAR(100),          -- 第三方流水号
  error_message TEXT DEFAULT '',
  paid_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()

RLS：标准 NULLIF(current_setting('app.tenant_id', true), '')::UUID 模式
索引：tenant_id/payment_id(UNIQUE)/store_id+created_at

Revision ID: v168
Revises: v167
"""

from alembic import op

revision = "v303"
down_revision = "v302"

branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS scan_pay_transactions (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            store_id        UUID,
            payment_id      VARCHAR(50) NOT NULL,
            auth_code       VARCHAR(100) NOT NULL,
            channel         VARCHAR(20) NOT NULL DEFAULT 'wechat'
                                CHECK (channel IN ('wechat', 'alipay', 'unionpay')),
            amount_fen      BIGINT      NOT NULL,
            status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending', 'paid', 'failed', 'cancelled')),
            cashier_id      VARCHAR(100),
            merchant_order_id VARCHAR(100),
            error_message   TEXT        NOT NULL DEFAULT '',
            paid_at         TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_scan_pay_payment_id
            ON scan_pay_transactions (payment_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_scan_pay_tenant_created
            ON scan_pay_transactions (tenant_id, created_at DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_scan_pay_store_created
            ON scan_pay_transactions (store_id, created_at DESC)
    """)
    op.execute("ALTER TABLE scan_pay_transactions ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE tablename = 'scan_pay_transactions' AND policyname = 'tenant_isolation'
          ) THEN
            CREATE POLICY tenant_isolation ON scan_pay_transactions
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
                WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
          END IF;
        END;
        $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS scan_pay_transactions CASCADE")
