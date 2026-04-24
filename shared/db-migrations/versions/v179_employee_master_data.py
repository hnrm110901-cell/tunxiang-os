"""v179 — 员工主数据扩展字段（employee_master_data）

ALTER TABLE employees 增加：
  gender / birth_date / id_card_number_encrypted / education /
  emergency_contact / emergency_phone / avatar_url /
  department_id / job_grade_id / employment_type /
  contract_start_date / contract_end_date / probation_end_date /
  health_cert_number / health_cert_expiry / food_safety_cert /
  tags / skill_tags / risk_level

索引：
  tenant_id+department_id, tenant_id+job_grade_id,
  health_cert_expiry, contract_end_date

Revision: v179
"""

from alembic import op

revision = "v179"
down_revision = "v178"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS gender TEXT")
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS birth_date DATE")
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS id_card_number_encrypted TEXT")
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS education TEXT")
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS emergency_contact TEXT")
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS emergency_phone TEXT")
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS avatar_url TEXT")
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS department_id UUID")
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS job_grade_id UUID")
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS employment_type TEXT DEFAULT 'full_time'")
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS contract_start_date DATE")
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS contract_end_date DATE")
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS probation_end_date DATE")
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS health_cert_number TEXT")
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS health_cert_expiry DATE")
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS food_safety_cert BOOLEAN DEFAULT FALSE")
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS tags JSONB DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS skill_tags JSONB DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS risk_level TEXT DEFAULT 'normal'")

    op.execute("CREATE INDEX IF NOT EXISTS idx_employees_tenant_department ON employees (tenant_id, department_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_employees_tenant_job_grade ON employees (tenant_id, job_grade_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_employees_health_cert_expiry ON employees (health_cert_expiry)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_employees_contract_end_date ON employees (contract_end_date)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_employees_contract_end_date")
    op.execute("DROP INDEX IF EXISTS idx_employees_health_cert_expiry")
    op.execute("DROP INDEX IF EXISTS idx_employees_tenant_job_grade")
    op.execute("DROP INDEX IF EXISTS idx_employees_tenant_department")
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS risk_level")
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS skill_tags")
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS tags")
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS food_safety_cert")
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS health_cert_expiry")
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS health_cert_number")
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS probation_end_date")
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS contract_end_date")
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS contract_start_date")
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS employment_type")
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS job_grade_id")
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS department_id")
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS avatar_url")
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS emergency_phone")
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS emergency_contact")
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS education")
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS id_card_number_encrypted")
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS birth_date")
    op.execute("ALTER TABLE employees DROP COLUMN IF EXISTS gender")
