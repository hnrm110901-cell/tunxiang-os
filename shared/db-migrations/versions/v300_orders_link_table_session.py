"""v150 — orders 表关联桌台会话 (Orders Link Table Session)

桌台中心化架构升级 Phase 2：
- orders 表新增 dining_session_id (UUID FK → dining_sessions.id)
- orders 表新增 order_sequence（第几轮点菜：1=主单，2+=加菜单）
- orders 表新增 is_add_order（是否为加菜单，冗余字段便于查询）
- orders 表保留 table_number（迁移兼容期，Phase 3 后废弃）
- 为历史数据提供清理说明（需业务层执行数据回填）

迁移策略：
- dining_session_id 允许 NULL（兼容现有历史订单和外卖/自提订单）
- 外卖/自提订单永远不需要 dining_session_id
- 堂食新订单从 v150 起必须关联 dining_session_id（业务层强制，非 DB 约束）
- 历史堂食订单 dining_session_id 为 NULL，通过 table_number 字段兼容

Revision: v150
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "v300"
down_revision = "v149"
branch_labels = None
depends_on = None


def upgrade() -> None:

    # ---------------------------------------------------------------
    # 1. orders 表新增 dining_session_id
    #    orders.dining_session_id → dining_sessions.id
    #    NULL 允许（外卖/自提/历史订单）
    # ---------------------------------------------------------------
    op.add_column(
        "orders",
        sa.Column(
            "dining_session_id",
            UUID(as_uuid=True),
            sa.ForeignKey("dining_sessions.id", name="fk_orders_table_session"),
            nullable=True,
            comment="桌台会话ID（v150新增，堂食必填，外卖/自提可为NULL）",
        ),
    )

    # ---------------------------------------------------------------
    # 2. orders 表新增 order_sequence
    #    同一桌台会话内的第几轮点单
    #    1 = 主单，2,3,... = 加菜单
    # ---------------------------------------------------------------
    op.add_column(
        "orders",
        sa.Column(
            "order_sequence",
            sa.Integer,
            nullable=False,
            server_default="1",
            comment="会话内点单序号：1=主单，2+=加菜单（v150新增）",
        ),
    )

    # ---------------------------------------------------------------
    # 3. orders 表新增 is_add_order（冗余便于查询，从 order_sequence 派生）
    # ---------------------------------------------------------------
    op.add_column(
        "orders",
        sa.Column(
            "is_add_order",
            sa.Boolean,
            nullable=False,
            server_default="false",
            comment="是否为加菜单（order_sequence > 1 时为 true，v150新增）",
        ),
    )

    # ---------------------------------------------------------------
    # 4. 创建索引
    # ---------------------------------------------------------------
    # 按会话查所有关联订单（最常用：展示一桌的全部点单）
    op.create_index(
        "idx_orders_table_session",
        "orders",
        ["dining_session_id"],
        postgresql_where=sa.text("dining_session_id IS NOT NULL"),
    )

    # ---------------------------------------------------------------
    # 5. 数据回填说明（不在迁移内执行，需运维脚本完成）
    #
    # 目标：为历史堂食订单创建 retroactive dining_sessions 记录
    # 执行时机：v150 迁移跑通后，业务低峰期执行回填脚本
    #
    # 回填逻辑（伪代码）：
    #   FOR each store:
    #     FOR each date:
    #       -- 按 table_number + 日期分组，每组对应一个历史会话
    #       SELECT DISTINCT table_number, DATE(created_at)
    #       FROM orders
    #       WHERE sales_channel = 'dine_in'
    #         AND table_number IS NOT NULL
    #         AND dining_session_id IS NULL
    #
    #       FOR each (table_number, date) group:
    #         INSERT INTO dining_sessions (...) VALUES (...)
    #         UPDATE orders SET dining_session_id = new_session.id
    #         WHERE table_number = X AND DATE(created_at) = Y
    #
    # 注：回填脚本位于 scripts/migrate/v150_backfill_dining_sessions.py
    # ---------------------------------------------------------------
    op.execute("""
        COMMENT ON COLUMN orders.dining_session_id IS
        '桌台会话ID（v150新增）。堂食新订单必须关联。历史堂食订单通过 v150_backfill 脚本回填。外卖/自提订单始终为 NULL。'
    """)

    op.execute("""
        COMMENT ON COLUMN orders.table_number IS
        '桌台号字符串（兼容字段，v002引入）。v150后新增堂食订单通过 dining_session_id 关联，此字段保留到 v153 废弃。'
    """)


def downgrade() -> None:
    op.drop_index("idx_orders_table_session", table_name="orders")
    op.drop_column("orders", "is_add_order")
    op.drop_column("orders", "order_sequence")
    op.drop_column("orders", "dining_session_id")
