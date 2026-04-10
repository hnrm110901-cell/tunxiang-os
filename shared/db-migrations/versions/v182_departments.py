"""v182 — 组织部门表（departments）

创建：
  departments — 组织架构树（物化路径模式）

字段说明：
  parent_id  — 上级部门（自引用），NULL 表示根节点
  dept_type  — 部门类型（group / region / city / store / kitchen / front 等）
  path       — 物化路径（如 /集团/华东区/上海/门店A/后厨）
  level      — 层级深度（0=根）
  sort_order — 同级排序

Revision: v182
"""

from alembic import op

revision = "v182"
down_revision = "v181"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS departments (
            id          UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id   UUID        NOT NULL,
            parent_id   UUID,
            name        TEXT        NOT NULL,
            dept_type   TEXT        NOT NULL,
            store_id    UUID,
            manager_id  UUID,
            sort_order  INT         DEFAULT 0,
            is_active   BOOLEAN     DEFAULT TRUE,
            path        TEXT,
            level       INT         DEFAULT 0,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_departments_tenant_parent "
        "ON departments (tenant_id, parent_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_departments_tenant_store "
        "ON departments (tenant_id, store_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_departments_tenant_type "
        "ON departments (tenant_id, dept_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_departments_path "
        "ON departments (path)"
    )
    op.execute("ALTER TABLE departments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE departments FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS departments_tenant_isolation ON departments")
    op.execute("""
        CREATE POLICY departments_tenant_isolation ON departments
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS departments")
