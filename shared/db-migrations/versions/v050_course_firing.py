"""v050 — Course Firing 打菜时机控制

Revision ID: v050
Revises: v047
Create Date: 2026-03-31
"""

from alembic import op

revision = "v050"
down_revision = "v047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE kds_tasks ADD COLUMN IF NOT EXISTS course_name VARCHAR(50) DEFAULT NULL;
        ALTER TABLE kds_tasks ADD COLUMN IF NOT EXISTS course_status VARCHAR(20) DEFAULT 'pending';
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS order_courses (
            id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID         NOT NULL,
            order_id        UUID         NOT NULL,
            course_name     VARCHAR(50)  NOT NULL,
            course_label    VARCHAR(50)  NOT NULL,
            sort_order      INTEGER      NOT NULL DEFAULT 1,
            status          VARCHAR(20)  NOT NULL DEFAULT 'waiting'
                CHECK (status IN ('waiting', 'fired', 'completed')),
            fired_at        TIMESTAMPTZ,
            fired_by        UUID,
            completed_at    TIMESTAMPTZ,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN      NOT NULL DEFAULT FALSE
        );

        COMMENT ON TABLE order_courses IS
            '订单课程管理：记录每笔订单各上菜课程的状态与开火记录';

        CREATE INDEX IF NOT EXISTS ix_order_courses_tenant_order
            ON order_courses (tenant_id, order_id)
            WHERE is_deleted = FALSE;

        CREATE UNIQUE INDEX IF NOT EXISTS uix_order_courses_order_course
            ON order_courses (order_id, course_name)
            WHERE is_deleted = FALSE;
    """)

    op.execute("""
        ALTER TABLE order_courses ENABLE ROW LEVEL SECURITY;
        ALTER TABLE order_courses FORCE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS order_courses_tenant_isolation ON order_courses;

        CREATE POLICY order_courses_tenant_isolation ON order_courses
            AS PERMISSIVE FOR ALL
            USING (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            )
            WITH CHECK (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS order_courses_tenant_isolation ON order_courses;")
    op.execute("DROP TABLE IF EXISTS order_courses;")
    op.execute("ALTER TABLE kds_tasks DROP COLUMN IF EXISTS course_status;")
    op.execute("ALTER TABLE kds_tasks DROP COLUMN IF EXISTS course_name;")
