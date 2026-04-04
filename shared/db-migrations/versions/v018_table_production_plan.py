"""v016: Create table_production_plans table (同桌同出协调计划)

New tables:
  - table_production_plans    TableFire 同桌同出协调计划

业务说明：
  当一张桌点了多个档口的菜（如热菜+凉菜+主食），
  系统为该桌创建一条协调计划，记录各档口的就绪状态和延迟开始时间，
  保证所有档口同时出品（同桌同出）。

RLS: 使用 app.tenant_id（与 v006 安全修复一致，NOT NULL guard）。

Revision ID: v016
Revises: v015
Create Date: 2026-03-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "v018"
down_revision: Union[str, None] = "v017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =====================================================================
    # table_production_plans — 同桌同出协调计划
    # =====================================================================
    op.create_table(
        "table_production_plans",
        # ── 基类字段（对齐 TenantBase）──
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True,
                  comment="租户ID（RLS隔离）"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
        # ── 业务字段 ──
        sa.Column("order_id", UUID(as_uuid=True), nullable=False, index=True,
                  comment="订单ID"),
        sa.Column("table_no", sa.String(20), nullable=False,
                  comment="桌号如A01"),
        sa.Column("store_id", UUID(as_uuid=True), nullable=False, index=True,
                  comment="门店ID"),
        sa.Column(
            "target_completion",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="协调基准时间（最慢档口预计完成时间）",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="coordinating",
            index=True,
            comment="计划状态：coordinating/all_ready/served",
        ),
        sa.Column(
            "dept_readiness",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment='JSON: {dept_id: ready_bool} 各档口就绪状态',
        ),
        sa.Column(
            "dept_delays",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment='JSON: {dept_id: delay_seconds} 各档口延迟开始时间(秒)',
        ),
        comment="同桌同出协调计划（TableFire）",
    )

    # 复合索引：门店+状态，供传菜督导视图高频查询
    op.create_index(
        "ix_table_production_plans_store_status",
        "table_production_plans",
        ["store_id", "status"],
    )

    # =====================================================================
    # RLS — 使用 app.tenant_id（与 v006 安全修复一致）
    # NULL guard: current_setting 在 session 未设置时返回空字符串，
    # 转换为 uuid 前需确保非 NULL，使用 NULLIF 防止空字符串造成语法错误。
    # =====================================================================
    table_name = "table_production_plans"

    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")

    # SELECT
    op.execute(f"""
        CREATE POLICY {table_name}_tenant_select ON {table_name}
        FOR SELECT
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
    """)

    # INSERT
    op.execute(f"""
        CREATE POLICY {table_name}_tenant_insert ON {table_name}
        FOR INSERT
        WITH CHECK (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
    """)

    # UPDATE
    op.execute(f"""
        CREATE POLICY {table_name}_tenant_update ON {table_name}
        FOR UPDATE
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
        WITH CHECK (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
    """)

    # DELETE
    op.execute(f"""
        CREATE POLICY {table_name}_tenant_delete ON {table_name}
        FOR DELETE
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
    """)


def downgrade() -> None:
    table_name = "table_production_plans"

    for action in ("delete", "update", "insert", "select"):
        op.execute(
            f"DROP POLICY IF EXISTS {table_name}_tenant_{action} ON {table_name}"
        )

    op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_table_production_plans_store_status", table_name=table_name)
    op.drop_table(table_name)
