"""v016: KDS任务持久化表 — kds_tasks

将KDS任务从内存OrderedDict迁移到PostgreSQL持久化存储。
新增字段支持催菜SLA闭环：promised_at、rush_count、last_rush_at。

Revision ID: v016
Revises: v015
Create Date: 2026-03-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v016"
down_revision: Union[str, None] = "v015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "kds_tasks"

# 安全RLS条件（与v006/v014保持一致）
_SAFE_CONDITION = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = current_setting('app.tenant_id')::UUID"
)


def upgrade() -> None:
    # ── 创建 kds_tasks 表 ──
    op.create_table(
        TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dept_id", postgresql.UUID(as_uuid=True), nullable=True),
        # 任务状态
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("priority", sa.String(20), nullable=False, server_default="normal"),
        # 时间线
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("promised_at", sa.DateTime(timezone=True), nullable=True),
        # 催菜SLA
        sa.Column("rush_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_rush_at", sa.DateTime(timezone=True), nullable=True),
        # 重做
        sa.Column("remake_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("remake_reason", sa.Text(), nullable=True),
        # 操作员
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=True),
        # 基类字段
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
    )

    # ── 索引 ──
    op.create_index("ix_kds_tasks_tenant_id", TABLE, ["tenant_id"])
    op.create_index("ix_kds_tasks_order_item_id", TABLE, ["order_item_id"])
    op.create_index("ix_kds_tasks_dept_id", TABLE, ["dept_id"])
    op.create_index("ix_kds_tasks_status", TABLE, ["status"])
    op.create_index(
        "ix_kds_tasks_tenant_dept_status",
        TABLE,
        ["tenant_id", "dept_id", "status"],
    )
    op.create_index(
        "ix_kds_tasks_tenant_status_created",
        TABLE,
        ["tenant_id", "status", "created_at"],
    )
    # 局部索引：只索引有承诺时间且未完成的任务，用于SLA超时扫描
    op.execute(
        "CREATE INDEX ix_kds_tasks_promised_at "
        "ON kds_tasks (promised_at) "
        "WHERE promised_at IS NOT NULL AND status NOT IN ('done', 'cancelled')"
    )

    # ── RLS策略（与v006/v014安全模式一致）──
    op.execute(
        f"CREATE POLICY {TABLE}_rls_select ON {TABLE} "
        f"FOR SELECT USING ({_SAFE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY {TABLE}_rls_insert ON {TABLE} "
        f"FOR INSERT WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY {TABLE}_rls_update ON {TABLE} "
        f"FOR UPDATE USING ({_SAFE_CONDITION}) WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(
        f"CREATE POLICY {TABLE}_rls_delete ON {TABLE} "
        f"FOR DELETE USING ({_SAFE_CONDITION})"
    )
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    # 删除RLS策略
    for suffix in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS {TABLE}_rls_{suffix} ON {TABLE}")

    op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")

    # 删除索引
    op.drop_index("ix_kds_tasks_promised_at", TABLE)
    op.drop_index("ix_kds_tasks_tenant_status_created", TABLE)
    op.drop_index("ix_kds_tasks_tenant_dept_status", TABLE)
    op.drop_index("ix_kds_tasks_status", TABLE)
    op.drop_index("ix_kds_tasks_dept_id", TABLE)
    op.drop_index("ix_kds_tasks_order_item_id", TABLE)
    op.drop_index("ix_kds_tasks_tenant_id", TABLE)

    # 删除表
    op.drop_table(TABLE)
