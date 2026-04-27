"""v285 — 拼桌执行日志（TableMergeLog）

记录每次拼桌执行的结果（成功/跳过），支持按日志回滚拆桌。

Revision ID: v285
Revises: v284
Create Date: 2026-04-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "v285"
down_revision: Union[str, None] = "v284"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "table_merge_logs"


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
        sa.Column("store_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "preset_id", UUID(as_uuid=True),
            sa.ForeignKey("table_merge_presets.id"), nullable=True,
            comment="关联预设（手动合并时为NULL）",
        ),
        sa.Column(
            "trigger_type", sa.String(20), nullable=False,
            comment="触发方式：auto(市别切换)/manual(店长手动)",
        ),
        sa.Column(
            "market_session_id", UUID(as_uuid=True), nullable=True,
            comment="触发时的市别ID",
        ),
        sa.Column(
            "executed_merges", JSONB, nullable=False, server_default="'[]'::jsonb",
            comment="实际执行的拼桌操作",
        ),
        sa.Column(
            "skipped_merges", JSONB, server_default="'[]'::jsonb",
            comment="跳过的（桌台occupied无法拼）",
        ),
        sa.Column(
            "executed_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "executed_by", UUID(as_uuid=True), nullable=True,
            comment="操作员ID（auto时为NULL）",
        ),
        sa.Column(
            "rollback_at", sa.DateTime(timezone=True), nullable=True,
            comment="回滚（拆回原状）时间",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # 按门店+执行时间查询
    op.create_index(
        "idx_tml_store_date", TABLE, ["store_id", "executed_at"],
    )
    # 按预设查询（仅非NULL）
    op.execute(
        "CREATE INDEX idx_tml_preset ON table_merge_logs (preset_id) "
        "WHERE preset_id IS NOT NULL"
    )

    _enable_rls(TABLE)


def downgrade() -> None:
    _disable_rls(TABLE)
    op.drop_table(TABLE)
