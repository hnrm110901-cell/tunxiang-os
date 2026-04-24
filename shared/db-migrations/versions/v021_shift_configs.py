"""shift_configs 班次配置表

Revision ID: 20260330_001
Revises:
Create Date: 2026-03-30

RLS Policy：使用 app.tenant_id（符合 CLAUDE.md §14 审计约束）。
禁止 NULL 绕过：tenant_id NOT NULL 已由 TenantBase 保证。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision = "v021"
down_revision = "v020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shift_configs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("shift_name", sa.String(50), nullable=False),
        sa.Column("start_time", sa.Time, nullable=False),
        sa.Column("end_time", sa.Time, nullable=False),
        sa.Column("color", sa.String(10), nullable=False, server_default="#FF6B35"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )

    # ── RLS ──────────────────────────────────────────────────────────────────
    # 使用 app.tenant_id（current_setting），而非 session 变量。
    # 符合 CRITICAL RLS 安全约束（project_rls_vulnerability.md）。
    op.execute("ALTER TABLE shift_configs ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY shift_configs_tenant_isolation ON shift_configs
            USING (tenant_id = current_setting('app.tenant_id')::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS shift_configs_tenant_isolation ON shift_configs;")
    op.drop_table("shift_configs")
