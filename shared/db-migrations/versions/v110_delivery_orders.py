"""v110: 外卖订单表补充字段 — 金额明细/配送时效/骑手信息

在现有 delivery_orders 表上补充前端接单面板所需字段：
  - subtotal_fen         菜品合计（分），不含配送费/折扣
  - delivery_fee_fen     配送费（分）
  - platform_discount_fen 平台补贴/折扣（分）
  - estimated_delivery_min 预估配送分钟数
  - delivering_at        骑手取单时间戳

补充说明：
  - rider_name / rider_phone 已在 v009 中存在
  - accepted_at / ready_at / completed_at 已在 v084 中存在
  - RLS 策略沿用 NULLIF(current_setting('app.tenant_id', true), '')::uuid 模式

Revision ID: v110
Revises: v109
Create Date: 2026-04-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v110"
down_revision: Union[str, None] = "v109"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "delivery_orders"


def upgrade() -> None:
    # ── 补充金额明细字段 ──────────────────────────────────────────────────────
    op.add_column(
        _TABLE,
        sa.Column(
            "subtotal_fen",
            sa.Integer(),
            nullable=True,
            comment="菜品合计（分），不含配送费和折扣",
        ),
    )
    op.add_column(
        _TABLE,
        sa.Column(
            "delivery_fee_fen",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="配送费（分）",
        ),
    )
    op.add_column(
        _TABLE,
        sa.Column(
            "platform_discount_fen",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="平台补贴/折扣（分）",
        ),
    )

    # ── 补充配送时效字段 ──────────────────────────────────────────────────────
    op.add_column(
        _TABLE,
        sa.Column(
            "estimated_delivery_min",
            sa.Integer(),
            nullable=True,
            comment="预估配送分钟数",
        ),
    )

    # ── 补充骑手取单时间戳 ────────────────────────────────────────────────────
    op.add_column(
        _TABLE,
        sa.Column(
            "delivering_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="骑手取单时间（对应 delivering 状态转换时刻）",
        ),
    )

    # ── 补充取消原因字段（前端 cancel 接口使用，与旧 cancel_reason 同义但兼容新接口）──
    # cancel_reason 已存在于 v009，此处跳过重复添加
    # 仅添加 cancel_by 字段区分操作来源
    op.add_column(
        _TABLE,
        sa.Column(
            "cancel_by",
            sa.String(20),
            nullable=True,
            comment="取消操作来源: staff / customer / platform / system",
        ),
    )

    # ── 新增复合索引（门店+状态+创建时间 — 接单面板列表查询热路径）────────────
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_delivery_order_store_status_created "
        "ON delivery_orders (store_id, status, created_at DESC);"
    )

    # ── 新增平台订单号短号索引 ────────────────────────────────────────────────
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_delivery_order_platform_order_no "
        "ON delivery_orders (platform_order_no) "
        "WHERE platform_order_no IS NOT NULL;"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_delivery_order_platform_order_no;")
    op.execute("DROP INDEX IF EXISTS idx_delivery_order_store_status_created;")

    for col in (
        "subtotal_fen",
        "delivery_fee_fen",
        "platform_discount_fen",
        "estimated_delivery_min",
        "delivering_at",
        "cancel_by",
    ):
        op.drop_column(_TABLE, col)
