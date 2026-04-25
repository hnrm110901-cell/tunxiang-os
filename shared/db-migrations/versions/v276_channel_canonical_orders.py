"""v276 — Sprint E1 渠道 canonical schema：channel_canonical_orders

E1 外卖渠道统一抽象层（Tier 2，纯加法）：

  目的：
    - 美团/饿了么/抖音/小红书/微信自有等多渠道订单进入屯象 OS 时，
      先落到统一 canonical 表，保留全量原始报文（payload）；
    - 上层适配器（pinjin/aiqiwei/meituan/eleme/douyin/...）后续以
      纯函数方式将 payload → CanonicalOrderRequest，本表为契约边界；
    - canonical_order_id 关联到本地 orders.id（灰度期可空），为 E2/E3
      留出口径升级空间，但本迁移不强制建立 FK 以避免与 tx-trade 现有
      orders 表的初始化顺序耦合（orders 表分散在多个 v* 迁移构建）。

  字段定义：
    - total_fen INTEGER NOT NULL         订单总额（分）
    - subsidy_fen INTEGER DEFAULT 0      渠道补贴 / 平台让利（不计入商家收入）
    - merchant_share_fen INTEGER DEFAULT 0  商家承担补贴部分（如商家自营满减）
    - commission_fen INTEGER DEFAULT 0   平台抽佣（商家成本）
    - settlement_fen GENERATED          实收 = total - subsidy - commission
                                        （ STORED；保留落地以便对账时确定性）
    - status                             received / accepted / rejected /
                                         delivered / cancelled / disputed
    - payload JSONB NOT NULL             渠道原始报文（升级 mapping 不丢数据）

  唯一约束：
    UNIQUE (tenant_id, channel_code, external_order_id) WHERE NOT is_deleted
    — 软删后允许同号重新入库（业务侧极少见但需留出口）

  RLS（CLAUDE.md §10 + 修复期 §14 严禁 NULL 绕过）：
    - ENABLE ROW LEVEL SECURITY
    - POLICY USING + WITH CHECK 双向对称
    - 当前会话必须 set_config('app.tenant_id', '...', true)，否则
      `current_setting('app.tenant_id', true)` 返回空，NULLIF + ::uuid 抛错
    - 严禁 NULL 绕过：不接受 app.tenant_id 缺失时仍可读写

  与现有适配器的关系（红线：本迁移不修改任何已存在的适配器/路由）：
    - 现有 services/tx-trade/adapters/pinjin/aiqiwei/meituan 等保持不变
    - tx-trade 新增 channel_canonical_routes.py 仅作为 canonical 入口，
      由后续 Sprint 渐进式将既有 webhook 改写为生成 CanonicalOrderRequest
    - 本迁移不引入对 orders 表的外键，避免约束循环

Revision ID: v276
Revises: v275
Create Date: 2026-04-25
"""

import sqlalchemy as sa
from alembic import op

revision = "v276"
down_revision = "v275"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "channel_canonical_orders" not in existing:
        op.execute("""
            CREATE TABLE channel_canonical_orders (
                id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
                tenant_id UUID NOT NULL,
                store_id UUID NOT NULL,
                channel_code TEXT NOT NULL,
                external_order_id TEXT NOT NULL,
                canonical_order_id UUID NULL,
                status TEXT NOT NULL DEFAULT 'received',
                total_fen INTEGER NOT NULL,
                subsidy_fen INTEGER NOT NULL DEFAULT 0,
                merchant_share_fen INTEGER NOT NULL DEFAULT 0,
                commission_fen INTEGER NOT NULL DEFAULT 0,
                settlement_fen INTEGER GENERATED ALWAYS AS
                    (total_fen - subsidy_fen - commission_fen) STORED,
                payload JSONB NOT NULL,
                received_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted BOOLEAN NOT NULL DEFAULT FALSE
            );
        """)

        # 状态枚举（与 ChannelCode/ status Literal 在 Pydantic 侧保持一致）
        op.execute("""
            ALTER TABLE channel_canonical_orders
            ADD CONSTRAINT ck_channel_canonical_orders_status
            CHECK (status IN (
                'received', 'accepted', 'rejected',
                'delivered', 'cancelled', 'disputed'
            ));
        """)

        # 金额非负约束
        op.execute("""
            ALTER TABLE channel_canonical_orders
            ADD CONSTRAINT ck_channel_canonical_orders_amounts_nonneg
            CHECK (
                total_fen >= 0
                AND subsidy_fen >= 0
                AND merchant_share_fen >= 0
                AND commission_fen >= 0
            );
        """)

        # 唯一索引（软删允许重新入库）
        op.execute("""
            CREATE UNIQUE INDEX uq_channel_canonical_orders_external
            ON channel_canonical_orders (tenant_id, channel_code, external_order_id)
            WHERE is_deleted IS NOT TRUE;
        """)

        # 列表查询索引（store + 时间倒序）
        op.create_index(
            "ix_channel_canonical_orders_store_received",
            "channel_canonical_orders",
            ["tenant_id", "store_id", "received_at"],
            postgresql_using="btree",
        )

        # canonical_order_id 反查索引（关联本地订单时使用）
        op.execute("""
            CREATE INDEX ix_channel_canonical_orders_canonical_order_id
            ON channel_canonical_orders (canonical_order_id)
            WHERE canonical_order_id IS NOT NULL;
        """)

    # RLS — USING + WITH CHECK 对称，严禁 NULL 绕过（§14）
    op.execute("ALTER TABLE channel_canonical_orders ENABLE ROW LEVEL SECURITY;")
    op.execute(
        "DROP POLICY IF EXISTS channel_canonical_orders_tenant_isolation "
        "ON channel_canonical_orders;"
    )
    op.execute(
        """
        CREATE POLICY channel_canonical_orders_tenant_isolation
            ON channel_canonical_orders
            USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            )
            WITH CHECK (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            );
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS channel_canonical_orders_tenant_isolation "
        "ON channel_canonical_orders;"
    )
    op.execute(
        "ALTER TABLE IF EXISTS channel_canonical_orders DISABLE ROW LEVEL SECURITY;"
    )
    op.execute("DROP INDEX IF EXISTS ix_channel_canonical_orders_canonical_order_id;")
    op.execute("DROP INDEX IF EXISTS ix_channel_canonical_orders_store_received;")
    op.execute("DROP INDEX IF EXISTS uq_channel_canonical_orders_external;")
    op.execute(
        "ALTER TABLE IF EXISTS channel_canonical_orders "
        "DROP CONSTRAINT IF EXISTS ck_channel_canonical_orders_amounts_nonneg;"
    )
    op.execute(
        "ALTER TABLE IF EXISTS channel_canonical_orders "
        "DROP CONSTRAINT IF EXISTS ck_channel_canonical_orders_status;"
    )
    op.execute("DROP TABLE IF EXISTS channel_canonical_orders;")
