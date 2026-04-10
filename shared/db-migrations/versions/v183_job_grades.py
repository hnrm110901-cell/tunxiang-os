"""v183 — 职级体系表（job_grades）

创建：
  job_grades — 职级定义（岗位类别+级别+薪资范围）

字段说明：
  category              — 岗位类别（kitchen / front / management / logistics 等）
  level                 — 级别（1=初级, 2=中级, 3=高级 ...）
  base_salary_range_min — 基本工资下限（分）
  base_salary_range_max — 基本工资上限（分）
  requirements          — 任职要求 JSONB（证书/经验/技能）

Revision: v183
"""

from alembic import op

revision = "v183"
down_revision = "v182"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS job_grades (
            id                     UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id              UUID        NOT NULL,
            name                   TEXT        NOT NULL,
            category               TEXT        NOT NULL,
            level                  INT         NOT NULL,
            base_salary_range_min  BIGINT,
            base_salary_range_max  BIGINT,
            description            TEXT,
            requirements           JSONB       DEFAULT '[]'::jsonb,
            is_active              BOOLEAN     DEFAULT TRUE,
            created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, name)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_grades_tenant_category "
        "ON job_grades (tenant_id, category)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_grades_tenant_level "
        "ON job_grades (tenant_id, level)"
    )
    op.execute("ALTER TABLE job_grades ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE job_grades FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS job_grades_tenant_isolation ON job_grades")
    op.execute("""
        CREATE POLICY job_grades_tenant_isolation ON job_grades
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS job_grades")
