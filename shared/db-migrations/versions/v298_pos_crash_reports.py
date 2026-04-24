"""v260 — POS 崩溃遥测表：pos_crash_reports

新建：
  pos_crash_reports — 前端 ErrorBoundary 上报的 POS 崩溃记录

用途：
  apps/web-pos ErrorBoundary 捕获未处理异常后，通过
  POST /api/v1/telemetry/pos-crash 写入本表。
  运维值班与 Sprint A1 健康度看板据此定位真实客户故障。

所有表含 tenant_id + RLS（app.tenant_id）。

Revision ID: v260
Revises: v259
Create Date: 2026-04-18
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "v298"
down_revision = "v259"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "pos_crash_reports" not in existing:
        op.create_table(
            "pos_crash_reports",
            sa.Column("report_id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=True,
                      comment="关联 stores.id，可空（登录前崩溃）"),
            sa.Column("device_id", sa.Text, nullable=False,
                      comment="POS 设备指纹/序列号，限流维度"),
            sa.Column("route", sa.Text, nullable=True,
                      comment="崩溃时前端路由（如 /cashier/checkout）"),
            sa.Column("error_stack", sa.Text, nullable=True,
                      comment="错误堆栈（前端 window.onerror 捕获）"),
            sa.Column("user_action", sa.Text, nullable=True,
                      comment="崩溃前最后一个用户动作摘要"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
        )
        op.create_index(
            "ix_pos_crash_reports_tenant_created",
            "pos_crash_reports",
            ["tenant_id", sa.text("created_at DESC")],
        )
        op.create_index(
            "ix_pos_crash_reports_device_created",
            "pos_crash_reports",
            ["device_id", sa.text("created_at DESC")],
        )

    op.execute("ALTER TABLE pos_crash_reports ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS pos_crash_reports_tenant ON pos_crash_reports;")
    op.execute("""
        CREATE POLICY pos_crash_reports_tenant ON pos_crash_reports
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS pos_crash_reports_tenant ON pos_crash_reports;")
    op.execute("ALTER TABLE IF EXISTS pos_crash_reports DISABLE ROW LEVEL SECURITY;")
    op.drop_index("ix_pos_crash_reports_device_created", table_name="pos_crash_reports")
    op.drop_index("ix_pos_crash_reports_tenant_created", table_name="pos_crash_reports")
    op.drop_table("pos_crash_reports")
