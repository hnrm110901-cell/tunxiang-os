"""v072: 预算管理表 — 预算编制 + 执行跟踪

新增表：
  budgets             — 预算表（门店/部门/期间/类别）
  budget_executions   — 预算执行记录

RLS 策略：
  全部使用 v006+ 标准安全模式（4操作 + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v072
Revises: v070
Create Date: 2026-03-31
"""

from alembic import op

revision = "v072"
down_revision = "v070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # budgets — 预算表
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS budgets (
            id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID        NOT NULL,
            store_id          UUID        NOT NULL,
            department        VARCHAR(100) NOT NULL,
            period            VARCHAR(20)  NOT NULL,
            period_start      DATE         NOT NULL,
            period_end        DATE         NOT NULL,
            category          VARCHAR(50)  NOT NULL,
            budget_amount_fen BIGINT       NOT NULL DEFAULT 0,
            status            VARCHAR(20)  NOT NULL DEFAULT 'draft',
            note              VARCHAR(500),
            is_deleted        BOOLEAN      NOT NULL DEFAULT FALSE,
            created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("ALTER TABLE budgets ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE budgets FORCE ROW LEVEL SECURITY;")

    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(f"""
            CREATE POLICY budgets_{action.lower()}_tenant ON budgets
            AS RESTRICTIVE FOR {action}
            USING (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
        """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_budgets_tenant
            ON budgets (tenant_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_budgets_tenant_store
            ON budgets (tenant_id, store_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_budgets_tenant_period
            ON budgets (tenant_id, period_start, period_end);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_budgets_tenant_store_category
            ON budgets (tenant_id, store_id, category);
    """)

    # ─────────────────────────────────────────────────────────────────
    # budget_executions — 预算执行记录
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS budget_executions (
            id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID        NOT NULL,
            budget_id         UUID        NOT NULL REFERENCES budgets(id) ON DELETE CASCADE,
            actual_amount_fen BIGINT       NOT NULL DEFAULT 0,
            variance_fen      BIGINT       NOT NULL DEFAULT 0,
            variance_pct      FLOAT        NOT NULL DEFAULT 0.0,
            recorded_date     DATE         NOT NULL,
            source_type       VARCHAR(30)  NOT NULL,
            description       VARCHAR(500),
            is_deleted        BOOLEAN      NOT NULL DEFAULT FALSE,
            created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("ALTER TABLE budget_executions ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE budget_executions FORCE ROW LEVEL SECURITY;")

    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(f"""
            CREATE POLICY budget_executions_{action.lower()}_tenant ON budget_executions
            AS RESTRICTIVE FOR {action}
            USING (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
        """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_budget_executions_tenant
            ON budget_executions (tenant_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_budget_executions_tenant_budget
            ON budget_executions (tenant_id, budget_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_budget_executions_tenant_date
            ON budget_executions (tenant_id, recorded_date);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS budget_executions CASCADE;")
    op.execute("DROP TABLE IF EXISTS budgets CASCADE;")
