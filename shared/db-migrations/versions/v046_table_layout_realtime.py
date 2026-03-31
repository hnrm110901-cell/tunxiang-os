"""v046: 桌位图形化布局 + 实时状态广播

新增表：
  table_layouts  — 每楼层一条记录，JSON存储图形坐标和桌位布局

RLS 策略：
  全部使用 v006+ 标准安全模式（4操作 + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v046
Revises: v045
Create Date: 2026-03-30
"""

from alembic import op

revision = "v046"
down_revision = "v045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # table_layouts — 桌位图形化布局（每楼层一条记录）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS table_layouts (
            id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      UUID        NOT NULL,
            store_id       UUID        NOT NULL,
            floor_no       INT         NOT NULL DEFAULT 1,
            floor_name     VARCHAR(50),
            canvas_width   INT         NOT NULL DEFAULT 1200,
            canvas_height  INT         NOT NULL DEFAULT 800,
            layout_json    JSONB       NOT NULL DEFAULT '{"tables":[],"walls":[],"areas":[]}',
            version        INT         NOT NULL DEFAULT 1,
            published_at   TIMESTAMPTZ,
            published_by   UUID,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(tenant_id, store_id, floor_no)
        );
    """)

    op.execute("ALTER TABLE table_layouts ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE table_layouts FORCE ROW LEVEL SECURITY;")

    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(f"""
            CREATE POLICY table_layouts_{action.lower()}_tenant ON table_layouts
            AS RESTRICTIVE FOR {action}
            USING (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
        """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_table_layouts_tenant_store
            ON table_layouts (tenant_id, store_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_table_layouts_tenant_store_floor
            ON table_layouts (tenant_id, store_id, floor_no);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS table_layouts CASCADE;")
