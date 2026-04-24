"""v076: 出品部门路由配置字段补充

为 production_depts 和 dish_dept_mappings 表补充厨房路由必需字段：

production_depts 新增：
  - kds_device_id   VARCHAR(100)  — 关联KDS设备标识（NULL=无KDS屏）
  - display_color   VARCHAR(20)   — KDS屏显示颜色标识（区分不同档口）
  - printer_type    VARCHAR(20)   — 打印机类型: network/usb/bluetooth
  - is_active       BOOLEAN       — 档口是否启用

dish_dept_mappings 新增：
  - is_primary      BOOLEAN       — 是否为菜品主档口（通常一对一）

背景：
  出品部门需要同时配置打印机（IP/端口已在 printer_address 字段）和 KDS 终端设备
  ID，才能实现"点菜→自动分单→打印+KDS显示"完整路由链路。

Revision ID: v076
Revises: v075
Create Date: 2026-03-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "v078"
down_revision= "v077"
branch_labels= None
depends_on= None

# 安全 RLS 条件（与 v006/v014/v016/v017 保持一致）
_SAFE_CONDITION = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = current_setting('app.tenant_id')::UUID"
)


def upgrade() -> None:
    # ── production_depts 补充字段 ──
    op.add_column(
        "production_depts",
        sa.Column(
            "kds_device_id",
            sa.String(100),
            nullable=True,
            comment="关联KDS设备标识（如设备序列号或自定义名称，NULL=无KDS屏）",
        ),
    )
    op.add_column(
        "production_depts",
        sa.Column(
            "display_color",
            sa.String(20),
            nullable=True,
            server_default="blue",
            comment="KDS屏显示颜色标识，用于区分不同档口：red/orange/green/blue/purple",
        ),
    )
    op.add_column(
        "production_depts",
        sa.Column(
            "printer_type",
            sa.String(20),
            nullable=True,
            server_default="network",
            comment="打印机类型：network（网络打印机，IP:Port）/ usb / bluetooth",
        ),
    )
    op.add_column(
        "production_depts",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default="true",
            comment="档口是否启用（停用后不接收新的分单任务）",
        ),
    )

    # 为 kds_device_id 建索引（KDS轮询时按设备ID查询任务）
    op.create_index(
        "ix_production_depts_kds_device_id",
        "production_depts",
        ["kds_device_id"],
        postgresql_where=sa.text("kds_device_id IS NOT NULL"),
    )

    # ── dish_dept_mappings 补充字段 ──
    op.add_column(
        "dish_dept_mappings",
        sa.Column(
            "is_primary",
            sa.Boolean(),
            nullable=False,
            server_default="true",
            comment="是否为菜品主档口（一道菜通常只属于一个主档口）",
        ),
    )

    # ── kds_tasks 补充 order_id 字段（方便按订单聚合查询） ──
    # kds_tasks 现在只有 order_item_id，加上 order_id 便于"按订单查所有档口任务"
    op.add_column(
        "kds_tasks",
        sa.Column(
            "order_id",
            PG_UUID(as_uuid=True),
            nullable=True,
            index=True,
            comment="关联订单ID（冗余存储，方便按订单聚合查询所有档口任务）",
        ),
    )
    op.add_column(
        "kds_tasks",
        sa.Column(
            "dish_name",
            sa.String(100),
            nullable=True,
            comment="菜品名称（冗余存储，避免联表查询，KDS展示用）",
        ),
    )
    op.add_column(
        "kds_tasks",
        sa.Column(
            "dish_id",
            PG_UUID(as_uuid=True),
            nullable=True,
            comment="菜品ID（冗余存储，便于按菜品统计出品数据）",
        ),
    )
    op.add_column(
        "kds_tasks",
        sa.Column(
            "quantity",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="菜品数量",
        ),
    )
    op.add_column(
        "kds_tasks",
        sa.Column(
            "table_number",
            sa.String(20),
            nullable=True,
            comment="桌号（冗余存储，KDS展示用）",
        ),
    )
    op.add_column(
        "kds_tasks",
        sa.Column(
            "order_no",
            sa.String(50),
            nullable=True,
            comment="订单号（冗余存储，KDS展示用）",
        ),
    )
    op.add_column(
        "kds_tasks",
        sa.Column(
            "notes",
            sa.Text(),
            nullable=True,
            comment="菜品备注（如不要辣、少盐等）",
        ),
    )

    # 复合索引：KDS轮询"某档口待出品任务"的核心查询路径
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_kds_tasks_dept_status_created "
        "ON kds_tasks (dept_id, status, created_at) WHERE is_deleted = false"
    ))
    # 按订单聚合任务进度查询
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_kds_tasks_order_id "
        "ON kds_tasks (order_id) WHERE order_id IS NOT NULL AND is_deleted = false"
    ))


def downgrade() -> None:
    # 删除 kds_tasks 新增索引
    op.drop_index("ix_kds_tasks_order_id", table_name="kds_tasks")
    op.drop_index("ix_kds_tasks_dept_status_created", table_name="kds_tasks")

    # 删除 kds_tasks 新增字段
    op.drop_column("kds_tasks", "notes")
    op.drop_column("kds_tasks", "order_no")
    op.drop_column("kds_tasks", "table_number")
    op.drop_column("kds_tasks", "quantity")
    op.drop_column("kds_tasks", "dish_id")
    op.drop_column("kds_tasks", "dish_name")
    op.drop_column("kds_tasks", "order_id")

    # 删除 dish_dept_mappings 新增字段
    op.drop_column("dish_dept_mappings", "is_primary")

    # 删除 production_depts 新增索引和字段
    op.drop_index("ix_production_depts_kds_device_id", table_name="production_depts")
    op.drop_column("production_depts", "is_active")
    op.drop_column("production_depts", "printer_type")
    op.drop_column("production_depts", "display_color")
    op.drop_column("production_depts", "kds_device_id")
