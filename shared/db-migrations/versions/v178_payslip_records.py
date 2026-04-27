"""v178 — 工资条记录表（payslip_records）

创建：
  payslip_records — 工资条主表（draft/issued/acknowledged 状态流转）

字段说明：
  pay_period   — 发薪周期，格式 YYYY-MM，如 2024-03
  gross_pay_fen — 应发合计（分）
  deductions_fen — 扣款合计（分，社保+公积金+个税+其他扣款）
  net_pay_fen   — 实发合计（分）
  breakdown     — JSONB，薪资明细项（base_salary_fen, position_allowance_fen,
                  meal_allowance_fen, transport_allowance_fen,
                  performance_bonus_fen, overtime_pay_fen,
                  seniority_subsidy_fen, full_attendance_bonus_fen,
                  absence_deduction_fen, late_deduction_fen,
                  social_insurance_fen, housing_fund_fen, tax_fen）
  meta          — JSONB，辅助字段（employee_name, role, work_days_in_month,
                  attendance_days, absence_days, late_count, early_leave_count）

Revision: v178
"""

from alembic import op

revision = "v178"
down_revision = "v177"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS payslip_records (
            id               UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id        UUID        NOT NULL,
            store_id         VARCHAR(64) NOT NULL,
            employee_id      VARCHAR(64) NOT NULL,
            pay_period       VARCHAR(7)  NOT NULL,
            -- 发薪周期 YYYY-MM，如 2026-03
            gross_pay_fen    BIGINT      NOT NULL DEFAULT 0,
            -- 应发合计（分）
            deductions_fen   BIGINT      NOT NULL DEFAULT 0,
            -- 扣款合计（分）= 社保 + 公积金 + 个税 + 其他扣款
            net_pay_fen      BIGINT      NOT NULL DEFAULT 0,
            -- 实发合计（分）
            breakdown        JSONB       NOT NULL DEFAULT '{}',
            -- 薪资明细：base_salary_fen / position_allowance_fen /
            --   meal_allowance_fen / transport_allowance_fen /
            --   performance_bonus_fen / overtime_pay_fen /
            --   seniority_subsidy_fen / full_attendance_bonus_fen /
            --   absence_deduction_fen / late_deduction_fen /
            --   social_insurance_fen / housing_fund_fen / tax_fen
            meta             JSONB       NOT NULL DEFAULT '{}',
            -- 辅助字段：employee_name / role / work_days_in_month /
            --   attendance_days / absence_days / late_count / early_leave_count
            status           VARCHAR(16) NOT NULL DEFAULT 'draft',
            -- draft / issued / acknowledged
            issued_at        TIMESTAMPTZ,
            acknowledged_at  TIMESTAMPTZ,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted       BOOLEAN     NOT NULL DEFAULT FALSE
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_payslip_records_tenant_store_period "
        "ON payslip_records (tenant_id, store_id, pay_period DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_payslip_records_tenant_employee_period "
        "ON payslip_records (tenant_id, employee_id, pay_period DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_payslip_records_tenant_period ON payslip_records (tenant_id, pay_period DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_payslip_records_status "
        "ON payslip_records (tenant_id, status) WHERE is_deleted = FALSE"
    )
    op.execute("ALTER TABLE payslip_records ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY payslip_records_rls ON payslip_records
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)
    op.execute("ALTER TABLE payslip_records FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS payslip_records")
