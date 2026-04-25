"""v277 — Sprint E4 渠道异议工作流：channel_disputes

E4 异议工作流（Tier 2 纯加法）：

  目的：
    - 美团/饿了么/抖音等平台审核退款、缺单、错单、配送延迟、品质投诉等
      异议事件统一进入屯象 OS 审核流；
    - 小额异议（≤ tenant 设定阈值，决策点 #5 默认 5000 分 = ¥50）
      auto_accept，省人工成本；大额走人工 manual_reviewing；
    - 任何裁决都要记 decision_by / decision_reason，便于复盘。

  关键字段：
    - canonical_order_id UUID NOT NULL REFERENCES channel_canonical_orders(id)
      （v276 创建的 canonical 表，硬关联，外键 ON DELETE RESTRICT 保证证据链）
    - claimed_amount_fen INTEGER NOT NULL  异议涉及金额（分）
    - state TEXT
        pending           — 默认初始（人工待审）
        auto_accepted     — 系统自动接受（claim ≤ threshold）
        manual_reviewing  — 已分配给运营手动审核
        accepted          — 人工或系统裁决：接受
        rejected          — 人工裁决：拒绝
        escalated         — 上报到上级（如直营督导）
    - auto_accept_threshold_fen INTEGER NULL
      记录这条异议被处理时使用的阈值快照（便于复盘历史决策）
      NULL 表示不适用 auto_accept（如 dispute_type=platform_audit 强制人工）
    - decision_by UUID NULL  操作员 user_id（auto_accepted 时为 NULL）
    - decision_reason TEXT NULL
    - decision_at TIMESTAMPTZ NULL

  唯一索引：(tenant_id, channel_code, external_dispute_id) WHERE NOT is_deleted

  RLS：USING + WITH CHECK 双向对称（与 v274/v276 一致），严禁 NULL 绕过

  关联：
    - 与 channel_canonical_orders 通过 FK 强关联
    - dispute 触发后写 CHANNEL.DISPUTE_OPENED（在 event_types.py 注册）
    - auto_accept 同时写 CHANNEL.DISPUTE_AUTO_ACCEPTED
    - resolve 时写 CHANNEL.DISPUTE_RESOLVED

Revision ID: v277
Revises: v276
Create Date: 2026-04-25
"""

import sqlalchemy as sa
from alembic import op

revision = "v277"
down_revision = "v276"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "channel_disputes" not in existing:
        op.execute("""
            CREATE TABLE channel_disputes (
                id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
                tenant_id UUID NOT NULL,
                store_id UUID NOT NULL,
                canonical_order_id UUID NOT NULL
                    REFERENCES channel_canonical_orders(id) ON DELETE RESTRICT,
                channel_code TEXT NOT NULL,
                external_dispute_id TEXT NOT NULL,
                dispute_type TEXT NOT NULL,
                claimed_amount_fen INTEGER NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                auto_accept_threshold_fen INTEGER NULL,
                decision_reason TEXT NULL,
                decision_by UUID NULL,
                decision_at TIMESTAMPTZ NULL,
                payload JSONB NOT NULL,
                opened_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted BOOLEAN NOT NULL DEFAULT FALSE
            );
        """)

        # state 枚举校验
        op.execute("""
            ALTER TABLE channel_disputes
            ADD CONSTRAINT ck_channel_disputes_state
            CHECK (state IN (
                'pending', 'auto_accepted', 'manual_reviewing',
                'accepted', 'rejected', 'escalated'
            ));
        """)

        # 金额非负
        op.execute("""
            ALTER TABLE channel_disputes
            ADD CONSTRAINT ck_channel_disputes_claimed_amount_nonneg
            CHECK (claimed_amount_fen >= 0);
        """)

        # 阈值非负（NULL 跳过 CHECK）
        op.execute("""
            ALTER TABLE channel_disputes
            ADD CONSTRAINT ck_channel_disputes_threshold_nonneg
            CHECK (auto_accept_threshold_fen IS NULL OR auto_accept_threshold_fen >= 0);
        """)

        # dispute_type 取值受控（仅做最小白名单，扩展时单独迁移）
        op.execute("""
            ALTER TABLE channel_disputes
            ADD CONSTRAINT ck_channel_disputes_dispute_type
            CHECK (dispute_type IN (
                'missing_item', 'wrong_item', 'delivery_late',
                'quality', 'platform_audit', 'refund_request',
                'chargeback', 'other'
            ));
        """)

        # 唯一索引
        op.execute("""
            CREATE UNIQUE INDEX uq_channel_disputes_external
            ON channel_disputes (tenant_id, channel_code, external_dispute_id)
            WHERE is_deleted IS NOT TRUE;
        """)

        # 列表查询索引（store + state + 时间倒序）
        op.create_index(
            "ix_channel_disputes_state_opened",
            "channel_disputes",
            ["tenant_id", "store_id", "state", "opened_at"],
            postgresql_using="btree",
        )

        # canonical_order_id 反查
        op.create_index(
            "ix_channel_disputes_canonical_order_id",
            "channel_disputes",
            ["canonical_order_id"],
        )

    # RLS
    op.execute("ALTER TABLE channel_disputes ENABLE ROW LEVEL SECURITY;")
    op.execute(
        "DROP POLICY IF EXISTS channel_disputes_tenant_isolation ON channel_disputes;"
    )
    op.execute(
        """
        CREATE POLICY channel_disputes_tenant_isolation ON channel_disputes
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
        "DROP POLICY IF EXISTS channel_disputes_tenant_isolation ON channel_disputes;"
    )
    op.execute(
        "ALTER TABLE IF EXISTS channel_disputes DISABLE ROW LEVEL SECURITY;"
    )
    op.execute("DROP INDEX IF EXISTS ix_channel_disputes_canonical_order_id;")
    op.execute("DROP INDEX IF EXISTS ix_channel_disputes_state_opened;")
    op.execute("DROP INDEX IF EXISTS uq_channel_disputes_external;")
    for ck in (
        "ck_channel_disputes_dispute_type",
        "ck_channel_disputes_threshold_nonneg",
        "ck_channel_disputes_claimed_amount_nonneg",
        "ck_channel_disputes_state",
    ):
        op.execute(
            f"ALTER TABLE IF EXISTS channel_disputes DROP CONSTRAINT IF EXISTS {ck};"
        )
    op.execute("DROP TABLE IF EXISTS channel_disputes;")
