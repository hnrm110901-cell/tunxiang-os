"""v254: review_cycles + review_scores tables

评审周期管理 + 在线打分持久化。支持多维度评分、多评审人、校准流程。

Revision ID: v254
Revises: v253
Create Date: 2026-04-13
"""

from alembic import op

revision = "v295"
down_revision = "v294"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── review_cycles — 评审周期表 ───────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS review_cycles (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            cycle_name      VARCHAR(100) NOT NULL,
            cycle_type      VARCHAR(20) NOT NULL,
            start_date      DATE NOT NULL,
            end_date        DATE NOT NULL,
            scoring_deadline DATE,
            status          VARCHAR(20) DEFAULT 'draft',
            scope_type      VARCHAR(20) DEFAULT 'brand',
            scope_id        UUID,
            dimensions      JSONB DEFAULT '[]'::jsonb,
            created_by      UUID,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW(),
            is_deleted      BOOLEAN DEFAULT FALSE
        );
    """)

    # ── review_scores — 评审打分表 ──────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS review_scores (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            cycle_id        UUID NOT NULL,
            employee_id     UUID NOT NULL,
            employee_name   VARCHAR(100),
            store_id        UUID,
            reviewer_id     UUID NOT NULL,
            reviewer_name   VARCHAR(100),
            reviewer_role   VARCHAR(30),
            dimension_scores JSONB DEFAULT '{}'::jsonb,
            total_score     NUMERIC(5,2),
            weighted_score  NUMERIC(5,2),
            comment         TEXT,
            status          VARCHAR(20) DEFAULT 'draft',
            submitted_at    TIMESTAMPTZ,
            calibrated_score NUMERIC(5,2),
            calibrated_by   UUID,
            calibrated_at   TIMESTAMPTZ,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW(),
            is_deleted      BOOLEAN DEFAULT FALSE
        );
    """)

    # ── 索引 ────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_review_cycles_tenant
            ON review_cycles (tenant_id);
        CREATE INDEX IF NOT EXISTS idx_review_cycles_status
            ON review_cycles (tenant_id, status);
        CREATE INDEX IF NOT EXISTS idx_review_cycles_type
            ON review_cycles (tenant_id, cycle_type);

        CREATE INDEX IF NOT EXISTS idx_review_scores_tenant
            ON review_scores (tenant_id);
        CREATE INDEX IF NOT EXISTS idx_review_scores_cycle
            ON review_scores (tenant_id, cycle_id);
        CREATE INDEX IF NOT EXISTS idx_review_scores_employee
            ON review_scores (tenant_id, cycle_id, employee_id);
        CREATE INDEX IF NOT EXISTS idx_review_scores_reviewer
            ON review_scores (tenant_id, reviewer_id);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_review_scores_cycle_emp_reviewer
            ON review_scores (tenant_id, cycle_id, employee_id, reviewer_id)
            WHERE is_deleted = FALSE;
    """)

    # ── RLS ──────────────────────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE review_cycles ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS rls_review_cycles ON review_cycles;
        CREATE POLICY rls_review_cycles ON review_cycles
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

        ALTER TABLE review_scores ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS rls_review_scores ON review_scores;
        CREATE POLICY rls_review_scores ON review_scores
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS review_scores CASCADE;")
    op.execute("DROP TABLE IF EXISTS review_cycles CASCADE;")
