"""print_tasks — 打印任务队列表（模块4.2 打印管理可视化中心）

若 print_tasks 表已存在则跳过（幂等）。

Revision ID: v247
Revises: v246
Create Date: 2026-04-12
"""

import sqlalchemy as sa
from alembic import op

revision = "v247"
down_revision = "v246"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # 幂等检查：表已存在则跳过
    inspector = sa.inspect(conn)
    if "print_tasks" in inspector.get_table_names():
        return

    op.create_table(
        "print_tasks",
        sa.Column("id", sa.UUID(), nullable=False, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(), nullable=False, comment="租户ID（RLS）"),
        sa.Column("printer_id", sa.UUID(), nullable=False, comment="打印机ID（关联 printers.id）"),
        sa.Column("content", sa.Text(), nullable=True, comment="打印内容（ESC/POS 或 ZPL）"),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
            comment="任务状态：pending/printing/done/failed",
        ),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0", comment="已重试次数"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="失败原因"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            onupdate=sa.text("NOW()"),
            nullable=False,
        ),
        comment="打印任务队列（模块4.2 打印管理可视化中心）",
    )

    # 索引
    op.create_index("ix_print_tasks_tenant_id", "print_tasks", ["tenant_id"])
    op.create_index("ix_print_tasks_printer_id", "print_tasks", ["printer_id"])
    op.create_index("ix_print_tasks_status", "print_tasks", ["status"])
    op.create_index(
        "ix_print_tasks_tenant_status_created",
        "print_tasks",
        ["tenant_id", "status", "created_at"],
    )

    # RLS Policy
    conn.execute(sa.text("ALTER TABLE print_tasks ENABLE ROW LEVEL SECURITY"))
    conn.execute(
        sa.text("""
        CREATE POLICY print_tasks_tenant_isolation ON print_tasks
        USING (tenant_id = current_setting('app.tenant_id')::uuid)
    """)
    )


def downgrade() -> None:
    conn = op.get_bind()
    try:
        conn.execute(sa.text("DROP POLICY IF EXISTS print_tasks_tenant_isolation ON print_tasks"))
    except Exception:  # noqa: BLE001
        pass
    op.drop_table("print_tasks")
