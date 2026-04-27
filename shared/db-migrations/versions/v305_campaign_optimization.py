"""v305 — 营销活动自优化追踪表: campaign_optimization_logs

记录每轮优化的AB测试评估、指标快照、调整方案、审批状态,
支持自动/人工审批两种模式的预算调配与内容优化决策留痕.

Revision ID: v305_campaign_optimization
Revises: v304_coupon_send_logs
Create Date: 2026-04-25
"""
from alembic import op

revision = "v305_campaign_optimization"
down_revision = "v304_coupon_send_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS campaign_optimization_logs (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            campaign_id             UUID NOT NULL,
            marketing_task_id       UUID,
            ab_test_id              UUID,
            optimization_round      INT NOT NULL DEFAULT 1,
            variant_a_metrics       JSONB NOT NULL DEFAULT '{}',
            variant_b_metrics       JSONB NOT NULL DEFAULT '{}',
            winner                  VARCHAR(10) CHECK (winner IN ('a', 'b', 'none', 'inconclusive')),
            p_value                 FLOAT,
            sample_size_a           INT DEFAULT 0,
            sample_size_b           INT DEFAULT 0,
            adjustment_action       JSONB NOT NULL DEFAULT '{}',
            status                  VARCHAR(20) NOT NULL DEFAULT 'evaluating'
                                    CHECK (status IN (
                                        'evaluating', 'pending_approval', 'approved',
                                        'applied', 'rejected', 'auto_applied'
                                    )),
            approved_by             UUID,
            approved_at             TIMESTAMPTZ,
            applied_at              TIMESTAMPTZ,
            auto_apply_threshold    FLOAT DEFAULT 0.05,
            budget_shift_pct        INT DEFAULT 0,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_campaign_opt_logs_campaign
            ON campaign_optimization_logs(tenant_id, campaign_id, optimization_round)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_campaign_opt_logs_status
            ON campaign_optimization_logs(tenant_id, status)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_campaign_opt_logs_task
            ON campaign_optimization_logs(tenant_id, marketing_task_id)
            WHERE is_deleted = false AND marketing_task_id IS NOT NULL
    """)

    op.execute("ALTER TABLE campaign_optimization_logs ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS campaign_optimization_logs_tenant_isolation ON campaign_optimization_logs;
        CREATE POLICY campaign_optimization_logs_tenant_isolation ON campaign_optimization_logs
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE campaign_optimization_logs FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS campaign_optimization_logs CASCADE")
