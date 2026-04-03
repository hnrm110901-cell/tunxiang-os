"""v078: store_clone_tasks — 快速开店克隆任务追踪表

记录每次门店配置克隆操作的状态、进度和结果摘要。
支持异步查询克隆进度（前端轮询）。

Revision ID: v078
Revises: v077
Create Date: 2026-03-31
"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "v082"
down_revision: Union[str, None] = "v081"
branch_labels = None
depends_on = None

TABLE = "store_clone_tasks"

# 与 v006+ 一致的安全 RLS 条件（NULL guard 防止绕过）
_SAFE_CONDITION = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = current_setting('app.tenant_id')::UUID"
)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "source_store_id",
            UUID(as_uuid=True),
            nullable=False,
            index=True,
            comment="克隆来源门店",
        ),
        sa.Column(
            "target_store_id",
            UUID(as_uuid=True),
            nullable=False,
            index=True,
            comment="克隆目标门店（必须已存在）",
        ),
        sa.Column(
            "selected_items",
            JSONB,
            nullable=False,
            server_default="'[]'",
            comment="用户勾选的配置项列表",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
            index=True,
            comment="pending/running/completed/failed",
        ),
        sa.Column(
            "progress",
            sa.Integer,
            nullable=False,
            server_default="0",
            comment="0-100 进度百分比",
        ),
        sa.Column(
            "result_summary",
            JSONB,
            nullable=True,
            comment='{"tables": {"cloned": 10, "status": "ok"}, ...}',
        ),
        sa.Column(
            "error_message",
            sa.Text,
            nullable=True,
            comment="整体失败时的错误信息",
        ),
        sa.Column(
            "created_by",
            sa.String(100),
            nullable=True,
            comment="操作人员工ID",
        ),
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
        sa.Column("is_deleted", sa.Boolean, server_default="false", nullable=False),
    )

    op.create_index(
        "ix_store_clone_tasks_tenant_status",
        TABLE,
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_store_clone_tasks_target_store",
        TABLE,
        ["tenant_id", "target_store_id"],
    )

    # RLS：4 操作 + NULL guard + FORCE
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY;")
    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(
            f"CREATE POLICY {TABLE}_{action.lower()}_tenant ON {TABLE} "
            f"AS RESTRICTIVE FOR {action} "
            f"USING ({_SAFE_CONDITION});"
        )


def downgrade() -> None:
    for action in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS {TABLE}_{action}_tenant ON {TABLE};")
    op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY;")
    op.drop_table(TABLE)
