"""20260330: Create cook_time_baselines table (菜品制作时间统计基准)

New tables:
  - cook_time_baselines    菜品×时段P50/P90制作时间基准

业务说明：
  存储每道菜在特定档口、特定时段（hour_bucket 0-23）和日期类型
  （weekday/weekend）下的历史制作时间P50/P90基准。
  用于：
    1. 动态超时阈值（替代固定25分钟配置）
    2. 队列预估清空时间计算
    3. 同桌同出协调的烹饪时间预测

RLS: 使用 NULLIF + app.tenant_id（与 v016 安全模式一致）。

Revision ID: 20260330_cook_time_baselines
Revises: v016
Create Date: 2026-03-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "v019"
down_revision= "v018"
branch_labels= None
depends_on= None

TABLE_NAME = "cook_time_baselines"


def upgrade() -> None:
    # =====================================================================
    # cook_time_baselines — 菜品制作时间基准
    # =====================================================================
    op.create_table(
        TABLE_NAME,
        # ── 基类字段（对齐 TenantBase）──
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  comment="主键UUID"),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True,
                  comment="租户ID（RLS隔离）"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),

        # ── 分组维度 ──
        sa.Column("dish_id", UUID(as_uuid=True), nullable=False, index=True,
                  comment="菜品ID（关联 dishes 表）"),
        sa.Column("dept_id", UUID(as_uuid=True), nullable=False, index=True,
                  comment="出品档口ID（关联 production_depts 表）"),
        sa.Column("hour_bucket", sa.Integer, nullable=False,
                  comment="时段（0-23，提取自 kds_tasks.started_at 的小时）"),
        sa.Column("day_type", sa.String(10), nullable=False, server_default="weekday",
                  comment="日期类型：weekday（周一至周五）/ weekend（周六周日）"),

        # ── 统计数据 ──
        sa.Column("p50_seconds", sa.Integer, nullable=False,
                  comment="制作时间中位数（秒），用于预估正常耗时"),
        sa.Column("p90_seconds", sa.Integer, nullable=False,
                  comment="制作时间P90（秒），用于动态warn/critical阈值"),
        sa.Column("sample_count", sa.Integer, nullable=False, server_default="0",
                  comment="样本数（<10时标记为不可靠，降级到dept默认值）"),

        # ── 元数据 ──
        sa.Column("computed_at", sa.DateTime(timezone=True),
                  comment="本条基准最后一次重算时间"),

        comment="菜品制作时间统计基准（dish × 时段 P50/P90）",
    )

    # ── 核心查询索引：按 tenant+dish+dept+hour+day_type 快速定位 ──
    op.create_index(
        "ix_cook_time_baselines_lookup",
        TABLE_NAME,
        ["tenant_id", "dish_id", "dept_id", "hour_bucket", "day_type"],
    )

    # ── 档口维度索引：按档口查最新基准 ──
    op.create_index(
        "ix_cook_time_baselines_dept_computed",
        TABLE_NAME,
        ["tenant_id", "dept_id", "computed_at"],
    )

    # =====================================================================
    # RLS — 使用 NULLIF + app.tenant_id
    # NULLIF防止session未设置时空字符串转UUID报错（与v016保持一致）
    # =====================================================================
    op.execute(f"ALTER TABLE {TABLE_NAME} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE_NAME} FORCE ROW LEVEL SECURITY")

    # SELECT
    op.execute(f"""
        CREATE POLICY {TABLE_NAME}_tenant_select ON {TABLE_NAME}
        FOR SELECT
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
    """)

    # INSERT
    op.execute(f"""
        CREATE POLICY {TABLE_NAME}_tenant_insert ON {TABLE_NAME}
        FOR INSERT
        WITH CHECK (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
    """)

    # UPDATE
    op.execute(f"""
        CREATE POLICY {TABLE_NAME}_tenant_update ON {TABLE_NAME}
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
        CREATE POLICY {TABLE_NAME}_tenant_delete ON {TABLE_NAME}
        FOR DELETE
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        )
    """)


def downgrade() -> None:
    for action in ("delete", "update", "insert", "select"):
        op.execute(
            f"DROP POLICY IF EXISTS {TABLE_NAME}_tenant_{action} ON {TABLE_NAME}"
        )

    op.execute(f"ALTER TABLE {TABLE_NAME} DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_cook_time_baselines_dept_computed", table_name=TABLE_NAME)
    op.drop_index("ix_cook_time_baselines_lookup", table_name=TABLE_NAME)
    op.drop_table(TABLE_NAME)
