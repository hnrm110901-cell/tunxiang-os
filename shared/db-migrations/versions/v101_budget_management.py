"""v101: 预算管理 v1 — 门店预算编制 + 执行跟踪

新建 2 张表：
  budget_plans       — 预算计划（门店/期间/科目/预算金额）
  budget_executions  — 预算执行记录（每次更新实际金额时追加一条）

设计要点：
  - period_type: monthly/quarterly/yearly
  - category: revenue/ingredient_cost/labor_cost/fixed_cost/marketing_cost/total
  - budget_executions 追加式写入，不覆盖，保留全部执行历史
  - variance_fen = actual_fen - budget_fen（正数=超支，负数=节约）
  - 可通过最新一条 execution 快速获取当前执行状态

Revision ID: v101
Revises: v100
Create Date: 2026-04-01
"""

from alembic import op

revision = "v101"
down_revision = "v100b"
branch_labels = None
depends_on = None

_VALID_CATEGORIES = ("revenue", "ingredient_cost", "labor_cost", "fixed_cost", "marketing_cost", "total")
_VALID_PERIOD_TYPES = ("monthly", "quarterly", "yearly")


def upgrade() -> None:
    # ── 1. budget_plans ──────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS budget_plans (
            id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID         NOT NULL,
            store_id        UUID         NOT NULL,
            period_type     VARCHAR(20)  NOT NULL
                                CHECK (period_type IN ('monthly','quarterly','yearly')),
            period          VARCHAR(10)  NOT NULL,
            category        VARCHAR(30)  NOT NULL
                                CHECK (category IN
                                    ('revenue','ingredient_cost','labor_cost',
                                     'fixed_cost','marketing_cost','total')),
            budget_fen      BIGINT       NOT NULL DEFAULT 0,
            note            TEXT,
            created_by      UUID,
            approved_by     UUID,
            approved_at     TIMESTAMPTZ,
            status          VARCHAR(20)  NOT NULL DEFAULT 'draft',
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, store_id, period_type, period, category)
        )
    """)
    op.execute("ALTER TABLE budget_plans ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY budget_plans_rls ON budget_plans
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_budget_plans_store_period
            ON budget_plans(tenant_id, store_id, period_type, period)
    """)

    # ── 2. budget_executions — 执行追踪 ─────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS budget_executions (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            budget_plan_id  UUID        NOT NULL REFERENCES budget_plans(id),
            actual_fen      BIGINT      NOT NULL DEFAULT 0,
            variance_fen    BIGINT      NOT NULL DEFAULT 0,
            variance_pct    NUMERIC(7,4),
            tracked_at      DATE        NOT NULL DEFAULT CURRENT_DATE,
            note            TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("ALTER TABLE budget_executions ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY budget_executions_rls ON budget_executions
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_budget_executions_plan
            ON budget_executions(tenant_id, budget_plan_id, tracked_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS budget_executions CASCADE")
    op.execute("DROP TABLE IF EXISTS budget_plans CASCADE")
