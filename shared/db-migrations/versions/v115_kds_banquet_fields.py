"""v115 — KDS任务表新增宴席关联字段 + 活鲜称重关联字段

Revision ID: v115
Revises: v114
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "v115"
down_revision = "v114"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── kds_tasks 新增宴席关联字段 ──────────────────────────────────
    op.add_column("kds_tasks", sa.Column(
        "banquet_session_id", UUID(as_uuid=True), nullable=True,
        comment="关联宴席场次ID，NULL=普通堂食任务"
    ))
    op.add_column("kds_tasks", sa.Column(
        "banquet_section_id", UUID(as_uuid=True), nullable=True,
        comment="关联宴席菜单节ID（凉菜/热菜/海鲜等），用于按节统计进度"
    ))
    op.add_column("kds_tasks", sa.Column(
        "weigh_record_id", UUID(as_uuid=True), nullable=True,
        comment="关联活鲜称重记录ID（仅活鲜菜品有）"
    ))
    op.add_column("kds_tasks", sa.Column(
        "is_live_seafood", sa.Boolean, nullable=False, server_default="false",
        comment="是否为活鲜菜品（需要称重确认后才能开始制作）"
    ))
    op.add_column("kds_tasks", sa.Column(
        "weigh_confirmed", sa.Boolean, nullable=False, server_default="false",
        comment="活鲜称重是否已确认（True后才能开始制作）"
    ))

    # ── dish_dept_mappings 菜品→档口映射表（若不存在则创建）────────────
    # 该表决定每道菜分到哪个KDS档口
    op.execute("""
        CREATE TABLE IF NOT EXISTS dish_dept_mappings (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID NOT NULL,
            store_id    UUID,
            dish_id     UUID NOT NULL,
            dept_id     UUID NOT NULL,
            dept_name   VARCHAR(50) NOT NULL,
            is_primary  BOOLEAN NOT NULL DEFAULT TRUE,
            priority    INTEGER NOT NULL DEFAULT 0,
            created_at  TIMESTAMPTZ DEFAULT now(),
            updated_at  TIMESTAMPTZ DEFAULT now(),
            is_deleted  BOOLEAN NOT NULL DEFAULT FALSE,
            CONSTRAINT uq_dish_dept_mapping UNIQUE (tenant_id, dish_id, dept_id)
        )
    """)

    # ── dish_dept_mappings: add new columns if missing ───────────────
    op.execute("""
        ALTER TABLE dish_dept_mappings
            ADD COLUMN IF NOT EXISTS dept_id     UUID,
            ADD COLUMN IF NOT EXISTS dept_name   VARCHAR(50),
            ADD COLUMN IF NOT EXISTS store_id    UUID,
            ADD COLUMN IF NOT EXISTS priority    INTEGER NOT NULL DEFAULT 0
    """)

    # ── 索引 ────────────────────────────────────────────────────────
    op.execute("CREATE INDEX IF NOT EXISTS ix_kds_tasks_banquet_session ON kds_tasks (banquet_session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_kds_tasks_banquet_section ON kds_tasks (banquet_section_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_dish_dept_mappings_dish ON dish_dept_mappings (dish_id, tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_dish_dept_mappings_dept ON dish_dept_mappings (dept_id) WHERE dept_id IS NOT NULL")

    # ── RLS ─────────────────────────────────────────────────────────
    op.execute("ALTER TABLE dish_dept_mappings ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY dish_dept_mappings_tenant_isolation ON dish_dept_mappings
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)


def downgrade() -> None:
    op.drop_table("dish_dept_mappings")
    for col in ["banquet_session_id", "banquet_section_id",
                "weigh_record_id", "is_live_seafood", "weigh_confirmed"]:
        op.drop_column("kds_tasks", col)
