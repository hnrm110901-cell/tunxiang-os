"""v284 — 时段拼桌预设（TableMergePreset）

将已有的手动并台能力升级为可按市别自动触发的拼桌方案。
午市可能需要更多2-4人桌（快翻台），晚市需要拼成6-8人大桌（聚餐场景）。

新增表：
  table_merge_presets — 拼桌方案配置（含 merge_rules JSONB + 关联市别）

Revision ID: v284
Revises: v283
Create Date: 2026-04-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "v284"
down_revision: Union[str, None] = "v283"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "table_merge_presets"


def _enable_rls(table_name: str) -> None:
    """启用 RLS + 租户隔离策略（与 v149 保持一致）"""
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation_{table_name} ON {table_name} "
        f"USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)"
    )
    op.execute(
        f"CREATE POLICY tenant_insert_{table_name} ON {table_name} "
        f"FOR INSERT WITH CHECK "
        f"(tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)"
    )


def _disable_rls(table_name: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_insert_{table_name} ON {table_name}")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table_name} ON {table_name}")
    op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "store_id", UUID(as_uuid=True),
            sa.ForeignKey("stores.id"), nullable=False,
        ),
        sa.Column(
            "preset_name", sa.String(50), nullable=False,
            comment="方案名称：午市快翻方案/晚市聚餐方案",
        ),
        sa.Column(
            "market_session_id", UUID(as_uuid=True), nullable=True,
            comment="关联市别（NULL=仅手动触发）",
        ),
        sa.Column(
            "merge_rules", JSONB, nullable=False, server_default="'[]'::jsonb",
            comment="拼桌规则：[{group_name, table_nos:[], effective_seats, target_scene}]",
        ),
        sa.Column(
            "auto_trigger", sa.Boolean, nullable=False, server_default="false",
            comment="市别切换时是否自动执行",
        ),
        sa.Column(
            "priority", sa.Integer, nullable=False, server_default="0",
            comment="同市别多方案时优先级（数字越大越优先）",
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )

    # 部分索引：同门店+市别下活跃方案快速查找
    op.execute(
        "CREATE INDEX idx_tmp_store_market ON table_merge_presets "
        "(store_id, market_session_id) "
        "WHERE is_active = TRUE AND is_deleted = FALSE"
    )

    _enable_rls(TABLE)


def downgrade() -> None:
    _disable_rls(TABLE)
    op.drop_table(TABLE)
