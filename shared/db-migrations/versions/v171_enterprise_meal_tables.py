"""v171 — 企业餐饮（员工福利餐）

创建：
  enterprise_meal_menus    — 企业周菜单配置（按星期几的菜品安排）
  enterprise_meal_accounts — 员工餐饮账户（余额 + 次数）
  enterprise_meal_orders   — 员工点餐记录

Revision: v171
"""

from alembic import op

revision = "v171"
down_revision = "v170"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS enterprise_meal_menus (
            id              UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id       UUID        NOT NULL,
            store_id        UUID        NOT NULL,
            week_start      DATE        NOT NULL,   -- 周一日期
            weekday         SMALLINT    NOT NULL,   -- 1=周一 ... 7=周日
            meal_type       VARCHAR(16) NOT NULL DEFAULT 'lunch',  -- breakfast/lunch/dinner
            dish_ids        JSONB       NOT NULL DEFAULT '[]',
            is_published    BOOLEAN     NOT NULL DEFAULT FALSE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN     NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_enterprise_meal_menus_tenant_week ON enterprise_meal_menus (tenant_id, week_start DESC)")
    op.execute("ALTER TABLE enterprise_meal_menus ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY enterprise_meal_menus_rls ON enterprise_meal_menus
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)
    op.execute("ALTER TABLE enterprise_meal_menus FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE TABLE IF NOT EXISTS enterprise_meal_accounts (
            id                      UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id               UUID        NOT NULL,
            employee_id             UUID        NOT NULL,
            balance_fen             BIGINT      NOT NULL DEFAULT 0,
            meal_count_remaining    INT         NOT NULL DEFAULT 0,
            monthly_allowance_fen   BIGINT      NOT NULL DEFAULT 0,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN     NOT NULL DEFAULT FALSE,
            UNIQUE (tenant_id, employee_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_enterprise_meal_accounts_tenant ON enterprise_meal_accounts (tenant_id, employee_id)")
    op.execute("ALTER TABLE enterprise_meal_accounts ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY enterprise_meal_accounts_rls ON enterprise_meal_accounts
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)
    op.execute("ALTER TABLE enterprise_meal_accounts FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE TABLE IF NOT EXISTS enterprise_meal_orders (
            id              UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id       UUID        NOT NULL,
            store_id        UUID        NOT NULL,
            employee_id     UUID        NOT NULL,
            meal_date       DATE        NOT NULL,
            meal_type       VARCHAR(16) NOT NULL DEFAULT 'lunch',
            dish_ids        JSONB       NOT NULL DEFAULT '[]',
            amount_fen      BIGINT      NOT NULL DEFAULT 0,
            payment_method  VARCHAR(16) NOT NULL DEFAULT 'account',
            -- account / cash / card
            status          VARCHAR(16) NOT NULL DEFAULT 'confirmed',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN     NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_enterprise_meal_orders_tenant_date ON enterprise_meal_orders (tenant_id, meal_date DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_enterprise_meal_orders_employee ON enterprise_meal_orders (tenant_id, employee_id, meal_date DESC)")
    op.execute("ALTER TABLE enterprise_meal_orders ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY enterprise_meal_orders_rls ON enterprise_meal_orders
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)
    op.execute("ALTER TABLE enterprise_meal_orders FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS enterprise_meal_orders")
    op.execute("DROP TABLE IF EXISTS enterprise_meal_accounts")
    op.execute("DROP TABLE IF EXISTS enterprise_meal_menus")
