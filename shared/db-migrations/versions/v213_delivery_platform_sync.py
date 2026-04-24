"""外卖平台集成同步表 — 菜单推送任务 + 估清同步日志

变更：
  delivery_menu_sync_tasks   — 菜单同步任务记录（POS→外卖平台）
  delivery_soldout_sync_log  — 估清同步日志（POS→外卖平台）

Revision: v213
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "v213"
down_revision = "v212"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()

    # ─── 菜单同步任务表 ───

    if "delivery_menu_sync_tasks" not in existing:
        op.create_table(
            "delivery_menu_sync_tasks",
            sa.Column(
                "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
            ),
            sa.Column("tenant_id", sa.String(100), nullable=False),
            sa.Column("store_id", sa.String(100), nullable=False, comment="门店ID"),
            sa.Column("platform", sa.String(20), nullable=False, comment="目标平台: meituan/eleme/douyin"),
            sa.Column(
                "sync_mode",
                sa.String(20),
                nullable=False,
                server_default="incremental",
                comment="同步模式: full/incremental",
            ),
            sa.Column("items_count", sa.Integer, nullable=False, server_default="0", comment="本次同步菜品数"),
            sa.Column("items_snapshot", postgresql.JSONB, nullable=True, comment="菜品快照（推送时的完整菜品列表）"),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="pending",
                comment="pending/syncing/success/failed",
            ),
            sa.Column("error_message", sa.Text, nullable=True, comment="失败原因"),
            sa.Column("platform_response", postgresql.JSONB, nullable=True, comment="平台返回原始响应"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True, comment="同步完成时间"),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )

        op.create_index(
            "ix_menu_sync_tenant_store_platform",
            "delivery_menu_sync_tasks",
            ["tenant_id", "store_id", "platform"],
        )
        op.create_index(
            "ix_menu_sync_created_at",
            "delivery_menu_sync_tasks",
            ["created_at"],
        )

        # RLS
        op.execute("ALTER TABLE delivery_menu_sync_tasks ENABLE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY delivery_menu_sync_tasks_tenant_isolation
            ON delivery_menu_sync_tasks
            USING (tenant_id = current_setting('app.tenant_id', true))
        """)

        # ─── 估清同步日志表 ───

    if "delivery_soldout_sync_log" not in existing:
        op.create_table(
            "delivery_soldout_sync_log",
            sa.Column(
                "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
            ),
            sa.Column("tenant_id", sa.String(100), nullable=False),
            sa.Column("store_id", sa.String(100), nullable=False, comment="门店ID"),
            sa.Column("platform", sa.String(20), nullable=False, comment="目标平台: meituan/eleme/douyin"),
            sa.Column("batch_id", sa.String(100), nullable=False, comment="批次ID，同一次多平台推送共享"),
            sa.Column("soldout_items", postgresql.JSONB, nullable=True, comment="估清菜品列表快照"),
            sa.Column("items_count", sa.Integer, nullable=False, server_default="0", comment="估清菜品数"),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="pending",
                comment="pending/syncing/success/failed",
            ),
            sa.Column("error_message", sa.Text, nullable=True, comment="失败原因"),
            sa.Column("platform_response", postgresql.JSONB, nullable=True, comment="平台返回原始响应"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True, comment="同步完成时间"),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )

        op.create_index(
            "ix_soldout_sync_tenant_store",
            "delivery_soldout_sync_log",
            ["tenant_id", "store_id"],
        )
        op.create_index(
            "ix_soldout_sync_batch_id",
            "delivery_soldout_sync_log",
            ["batch_id"],
        )
        op.create_index(
            "ix_soldout_sync_created_at",
            "delivery_soldout_sync_log",
            ["created_at"],
        )

        # RLS
        op.execute("ALTER TABLE delivery_soldout_sync_log ENABLE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY delivery_soldout_sync_log_tenant_isolation
            ON delivery_soldout_sync_log
            USING (tenant_id = current_setting('app.tenant_id', true))
        """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS delivery_soldout_sync_log_tenant_isolation ON delivery_soldout_sync_log")
    op.drop_table("delivery_soldout_sync_log")
    op.execute("DROP POLICY IF EXISTS delivery_menu_sync_tasks_tenant_isolation ON delivery_menu_sync_tasks")
    op.drop_table("delivery_menu_sync_tasks")
