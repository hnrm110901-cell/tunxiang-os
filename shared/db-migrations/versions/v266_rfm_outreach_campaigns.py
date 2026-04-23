"""v266 — RFM 触达活动表（Sprint D3a）

CF + Haiku 4.5 生成的 RFM 触达建议需要落库追踪：
  1. 生成阶段（plan_generated）：CF 打分 + Haiku 写文案 → 待审
  2. 确认阶段（human_confirmed）：店长审批 + 触达
  3. 归因阶段（attributed）：复购订单 → 自动回写 `attributed_order_ids`

核心指标（复购率 +5pp）由 `mv_rfm_outreach_lift_monthly`（后续 PR 加）按
campaign_id 聚合计算。

Revision ID: v266_rfm_outreach
Revises: v265_mv_roi
Create Date: 2026-04-23
"""
from alembic import op

revision = "v266_rfm_outreach"
down_revision = "v265_mv_roi"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 主表
    op.execute("""
        CREATE TABLE IF NOT EXISTS rfm_outreach_campaigns (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            store_id            UUID,
            campaign_name       VARCHAR(200) NOT NULL,
            rfm_segment         VARCHAR(20) NOT NULL,
                                  -- S1/S2/S3/S4/S5（分层）
            target_customer_ids UUID[] NOT NULL,
            target_count        INTEGER NOT NULL DEFAULT 0
                                  CHECK (target_count >= 0),
            -- CF 推荐
            cf_scoring_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
                                  -- {"customer_id": {"score": 0.85, "top_items": [...]}}
            -- 消息
            message_template    TEXT NOT NULL DEFAULT '',
            message_model       VARCHAR(50) NOT NULL DEFAULT 'claude-haiku-4-5',
            -- 状态流
            status              VARCHAR(30) NOT NULL DEFAULT 'plan_generated'
                                  CHECK (status IN (
                                      'plan_generated',
                                      'human_confirmed',
                                      'sending',
                                      'sent',
                                      'attributed',
                                      'cancelled',
                                      'error'
                                  )),
            -- 执行记录
            confirmed_by        UUID,
            confirmed_at        TIMESTAMPTZ,
            sent_at             TIMESTAMPTZ,
            attributed_order_ids UUID[] DEFAULT ARRAY[]::UUID[],
            attributed_revenue_fen BIGINT DEFAULT 0
                                  CHECK (attributed_revenue_fen >= 0),
            -- 预估 ROI（Haiku 生成阶段写入，归因后覆盖）
            estimated_roi_summary JSONB DEFAULT '{}'::jsonb,
                                  -- {"estimated_revenue_fen": X, "cost_fen": Y}
            -- 基础字段
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    # 2. 索引
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_rfm_outreach_tenant_status
            ON rfm_outreach_campaigns (tenant_id, status, created_at DESC)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_rfm_outreach_store_rfm
            ON rfm_outreach_campaigns (tenant_id, store_id, rfm_segment, created_at DESC)
            WHERE is_deleted = false
    """)

    # 3. RLS（蓝图：app.tenant_id）
    op.execute("ALTER TABLE rfm_outreach_campaigns ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS rfm_outreach_tenant_isolation ON rfm_outreach_campaigns;
        CREATE POLICY rfm_outreach_tenant_isolation ON rfm_outreach_campaigns
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # 4. 注释
    op.execute("""
        COMMENT ON TABLE rfm_outreach_campaigns IS
            'Sprint D3a: RFM 触达活动表，CF 选客户 + Haiku 写文案 + 人工确认 + 归因回写';
        COMMENT ON COLUMN rfm_outreach_campaigns.cf_scoring_snapshot IS
            'CF 推荐打分快照：{"customer_id": {"score": 0.85, "top_items": ["dish_id_1"]}}';
        COMMENT ON COLUMN rfm_outreach_campaigns.rfm_segment IS
            'RFM 分层 S1-S5：S1 最活跃（7天内复购）/ S5 沉睡';
        COMMENT ON COLUMN rfm_outreach_campaigns.estimated_roi_summary IS
            'Haiku 生成阶段的预估 ROI，归因完成后被真实值覆盖';
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rfm_outreach_campaigns CASCADE")
