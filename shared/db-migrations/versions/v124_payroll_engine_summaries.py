"""v124 — 薪资引擎扩展表：月度汇总 + 绩效评分明细 + 扣款记录

在 v120 payroll_configs / payroll_records / payroll_line_items 基础上补充：
  payroll_summaries   — 员工月度薪资汇总（含计件/提成/绩效/扣款）
  perf_score_items    — 绩效评分明细（月度，支持多维度加权评分）
  payroll_deductions  — 扣款记录（迟到/违规/损耗赔偿，支持软删除撤销）

所有表含 tenant_id + RLS（使用 NULLIF(current_setting(...), '')::uuid 模式）。

Revision ID: v124
Revises: v123
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa

revision = "v124"
down_revision = "v123"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── payroll_summaries：员工月度薪资汇总 ──────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS payroll_summaries (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            employee_id             UUID NOT NULL,
            store_id                UUID NOT NULL,
            period_year             INT NOT NULL,
            period_month            INT NOT NULL,
            base_salary_fen         INT NOT NULL DEFAULT 0,
            piece_count             INT DEFAULT 0,
            piece_amount_fen        INT DEFAULT 0,
            commission_base_fen     INT DEFAULT 0,
            commission_amount_fen   INT DEFAULT 0,
            perf_score              NUMERIC(5,2),
            perf_bonus_fen          INT DEFAULT 0,
            deductions_fen          INT DEFAULT 0,
            total_salary_fen        INT NOT NULL,
            status                  VARCHAR(20) DEFAULT 'draft',
            notes                   TEXT,
            created_at              TIMESTAMPTZ DEFAULT NOW(),
            updated_at              TIMESTAMPTZ DEFAULT NOW(),
            is_deleted              BOOLEAN DEFAULT FALSE,
            UNIQUE(tenant_id, employee_id, period_year, period_month)
        )
    """)

    op.execute("ALTER TABLE payroll_summaries ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS payroll_summaries_tenant_isolation ON payroll_summaries;")
    op.execute("""
        CREATE POLICY payroll_summaries_tenant_isolation ON payroll_summaries
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
    """)
    # Ensure is_deleted column exists (table may predate this migration)
    op.execute("""
        ALTER TABLE payroll_summaries
            ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_payroll_summaries_tenant_period
        ON payroll_summaries(tenant_id, store_id, period_year, period_month)
        WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_payroll_summaries_employee
        ON payroll_summaries(tenant_id, employee_id, period_year, period_month)
        WHERE is_deleted = false
    """)

    # ── perf_score_items：绩效评分明细（月度） ──────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS perf_score_items (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            employee_id     UUID NOT NULL,
            period_year     INT NOT NULL,
            period_month    INT NOT NULL,
            item_name       VARCHAR(100) NOT NULL,
            score           NUMERIC(5,2) NOT NULL,
            weight          NUMERIC(5,4) DEFAULT 1.0,
            notes           VARCHAR(200),
            is_deleted      BOOLEAN DEFAULT FALSE
        )
    """)

    op.execute("ALTER TABLE perf_score_items ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS perf_score_items_tenant_isolation ON perf_score_items;")
    op.execute("""
        CREATE POLICY perf_score_items_tenant_isolation ON perf_score_items
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_perf_score_items_employee
        ON perf_score_items(tenant_id, employee_id, period_year, period_month)
        WHERE is_deleted = false
    """)

    # ── payroll_deductions：扣款记录 ─────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS payroll_deductions (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            employee_id     UUID NOT NULL,
            period_year     INT NOT NULL,
            period_month    INT NOT NULL,
            reason          VARCHAR(100) NOT NULL,
            amount_fen      INT NOT NULL,
            approved_by     VARCHAR(100),
            is_deleted      BOOLEAN DEFAULT FALSE,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    op.execute("ALTER TABLE payroll_deductions ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS payroll_deductions_tenant_isolation ON payroll_deductions;")
    op.execute("""
        CREATE POLICY payroll_deductions_tenant_isolation ON payroll_deductions
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_payroll_deductions_employee
        ON payroll_deductions(tenant_id, employee_id, period_year, period_month)
        WHERE is_deleted = false
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS payroll_deductions")
    op.execute("DROP TABLE IF EXISTS perf_score_items")
    op.execute("DROP TABLE IF EXISTS payroll_summaries")
