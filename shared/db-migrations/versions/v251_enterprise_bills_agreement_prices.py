"""v251 企业月结账单 + 协议价表

新增：
  enterprise_bills             — 企业月结账单（bill_no + 收款状态）
  enterprise_agreement_prices  — 企业协议菜品价格（per dish 特殊定价）

背景：enterprise_billing.py / enterprise_account.py 仍使用内存 dict，
      此迁移完成 DB 持久化，配合 v250 enterprise_accounts/enterprise_sign_records 表。
"""
from alembic import op
import sqlalchemy as sa

revision = "v251"
down_revision = "v250"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── enterprise_bills ──────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS enterprise_bills (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID        NOT NULL,
            bill_no             VARCHAR(60) NOT NULL,
            enterprise_id       UUID        NOT NULL REFERENCES enterprise_accounts(id),
            enterprise_name     VARCHAR(200) NOT NULL,
            month               VARCHAR(7)  NOT NULL,
            total_amount_fen    BIGINT      NOT NULL DEFAULT 0 CHECK (total_amount_fen >= 0),
            paid_amount_fen     BIGINT      NOT NULL DEFAULT 0 CHECK (paid_amount_fen >= 0),
            outstanding_fen     BIGINT      NOT NULL DEFAULT 0 CHECK (outstanding_fen >= 0),
            order_count         INT         NOT NULL DEFAULT 0,
            status              VARCHAR(20) NOT NULL DEFAULT 'issued',
            payment_method      VARCHAR(50),
            issued_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            paid_at             TIMESTAMPTZ,
            line_items          JSONB       NOT NULL DEFAULT '[]',
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_enterprise_bills_enterprise_month
            ON enterprise_bills(tenant_id, enterprise_id, month)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_enterprise_bills_tenant
            ON enterprise_bills(tenant_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_enterprise_bills_status
            ON enterprise_bills(tenant_id, status)
    """)
    op.execute("ALTER TABLE enterprise_bills ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY enterprise_bills_tenant_isolation
            ON enterprise_bills
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)

    # ── enterprise_agreement_prices ───────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS enterprise_agreement_prices (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID        NOT NULL,
            enterprise_id       UUID        NOT NULL REFERENCES enterprise_accounts(id),
            dish_id             VARCHAR(100) NOT NULL,
            price_fen           BIGINT      NOT NULL DEFAULT 0 CHECK (price_fen >= 0),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_enterprise_agreement_prices_dish
            ON enterprise_agreement_prices(tenant_id, enterprise_id, dish_id)
    """)
    op.execute("ALTER TABLE enterprise_agreement_prices ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY enterprise_agreement_prices_tenant_isolation
            ON enterprise_agreement_prices
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS enterprise_agreement_prices CASCADE")
    op.execute("DROP TABLE IF EXISTS enterprise_bills CASCADE")
