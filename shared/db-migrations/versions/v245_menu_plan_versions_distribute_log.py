"""菜谱方案版本管理 + 批量下发日志 — 模块3.4

新增表：
  - menu_plan_versions: 方案版本快照（每次发布创建一条）
  - menu_distribute_log: 方案下发日志（门店级）

说明：
  - menu_store_overrides 即 store_menu_overrides（已在 scheme_routes 使用的表），本次不重复创建
  - menu_plan_versions 的 snapshot_json 保存发布时的完整菜品列表快照，支持回滚
  - menu_distribute_log 记录每次下发的结果（门店/时间/状态/错误信息）

Revision ID: v245
Revises: v244
Create Date: 2026-04-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "v245"
down_revision = "v244b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()


    # ------------------------------------------------------------------
    # 表1：menu_plan_versions（方案版本快照）
    # ------------------------------------------------------------------

    if 'menu_plan_versions' not in existing:
        op.create_table(
            "menu_plan_versions",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True,
                server_default=sa.text("gen_random_uuid()"), nullable=False,
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, comment="租户ID（RLS隔离）"),
            sa.Column(
                "scheme_id", UUID(as_uuid=True), nullable=False,
                comment="关联菜谱方案 ID（menu_schemes.id）",
            ),
            sa.Column(
                "version_number", sa.Integer(), nullable=False,
                comment="版本号，从1递增，每次publish时递增",
            ),
            sa.Column(
                "change_summary", sa.Text(), nullable=True,
                comment="本次版本变更摘要（人工填写或自动生成）",
            ),
            sa.Column(
                "snapshot_json", JSONB(), nullable=False, server_default="'[]'::jsonb",
                comment="发布时的完整菜品列表快照，用于回滚",
            ),
            sa.Column(
                "published_by", sa.String(100), nullable=True,
                comment="发布操作人 ID",
            ),
            sa.Column(
                "created_at", sa.TIMESTAMP(timezone=True),
                nullable=False, server_default=sa.text("NOW()"),
            ),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        )
        op.create_index(
            "idx_menu_plan_versions_scheme_id",
            "menu_plan_versions", ["scheme_id", "tenant_id"],
        )
        op.create_index(
            "idx_menu_plan_versions_version",
            "menu_plan_versions", ["scheme_id", "version_number"],
            unique=True,
        )
        # RLS
        op.execute("ALTER TABLE menu_plan_versions ENABLE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY menu_plan_versions_tenant_isolation
              ON menu_plan_versions
              USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
        """)

        # ------------------------------------------------------------------
        # 表2：menu_distribute_log（方案下发日志）
        # ------------------------------------------------------------------

    if 'menu_distribute_log' not in existing:
        op.create_table(
            "menu_distribute_log",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True,
                server_default=sa.text("gen_random_uuid()"), nullable=False,
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, comment="租户ID（RLS隔离）"),
            sa.Column("scheme_id", UUID(as_uuid=True), nullable=False, comment="下发方案 ID"),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False, comment="目标门店 ID"),
            sa.Column(
                "version_number", sa.Integer(), nullable=True,
                comment="下发的版本号（NULL 表示初次下发，未创建版本快照时）",
            ),
            sa.Column(
                "status", sa.String(20), nullable=False, server_default="'success'",
                comment="下发状态：success / failed / pending",
            ),
            sa.Column("error_message", sa.Text(), nullable=True, comment="下发失败时的错误信息"),
            sa.Column("distributed_by", sa.String(100), nullable=True, comment="操作人 ID"),
            sa.Column(
                "distributed_at", sa.TIMESTAMP(timezone=True),
                nullable=False, server_default=sa.text("NOW()"),
            ),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        )
        op.create_index(
            "idx_menu_distribute_log_scheme_id",
            "menu_distribute_log", ["scheme_id", "tenant_id"],
        )
        op.create_index(
            "idx_menu_distribute_log_store_id",
            "menu_distribute_log", ["store_id", "tenant_id"],
        )
        # RLS
        op.execute("ALTER TABLE menu_distribute_log ENABLE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY menu_distribute_log_tenant_isolation
              ON menu_distribute_log
              USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
        """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS menu_distribute_log_tenant_isolation ON menu_distribute_log")
    op.execute("DROP POLICY IF EXISTS menu_plan_versions_tenant_isolation ON menu_plan_versions")
    op.drop_table("menu_distribute_log")
    op.drop_table("menu_plan_versions")
