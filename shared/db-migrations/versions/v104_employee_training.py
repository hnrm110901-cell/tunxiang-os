"""v104: 员工培训管理 DB 化 — 将 employee_depth.py 的 _training_store 迁移到 PostgreSQL

新建 1 张表：
  employee_trainings — 员工培训记录（课程分配/完成/认证）

设计要点：
  - (tenant_id, employee_id, course_id) 联合索引加速查询
  - status CHECK: pending/in_progress/completed/failed
  - category CHECK: food_safety/service/cooking/management/other
  - certificate_id 用于存储认证凭证 ID
  - RLS: NULLIF(app.tenant_id) 防 NULL 绕过

Revision ID: v104
Revises: v103
Create Date: 2026-04-01
"""

from alembic import op

revision = "v104"
down_revision = "v103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS employee_trainings (
            id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID         NOT NULL,
            employee_id      UUID         NOT NULL,
            course_id        VARCHAR(100) NOT NULL,
            course_name      VARCHAR(200) NOT NULL DEFAULT '',
            category         VARCHAR(50)  NOT NULL DEFAULT 'other'
                                 CHECK (category IN ('food_safety','service','cooking','management','other')),
            status           VARCHAR(20)  NOT NULL DEFAULT 'pending'
                                 CHECK (status IN ('pending','in_progress','completed','failed')),
            pass_threshold   INT          NOT NULL DEFAULT 60,
            score            INT,
            certificate_id   VARCHAR(100),
            assigned_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            started_at       TIMESTAMPTZ,
            completed_at     TIMESTAMPTZ,
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("ALTER TABLE employee_trainings ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY employee_trainings_rls ON employee_trainings
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_employee_trainings_employee
            ON employee_trainings(tenant_id, employee_id, status)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_employee_trainings_course
            ON employee_trainings(tenant_id, employee_id, course_id)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS employee_trainings CASCADE")
