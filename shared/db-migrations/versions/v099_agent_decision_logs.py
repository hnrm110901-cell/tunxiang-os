"""v099 — agent_decision_logs 表：Agent 决策留痕持久化

记录所有 Agent（Orchestrator + Skill Agent）的决策过程，
支持审计、回溯和 AI 效果评估。

Revision ID: v099
Revises: v098
Create Date: 2026-04-01
"""

from alembic import op

revision = "v099"
down_revision = "v098"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_decision_logs (
            id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID         NOT NULL,
            store_id         UUID,
            agent_id         VARCHAR(100) NOT NULL,
            decision_type    VARCHAR(100) NOT NULL,
            input_context    JSONB        NOT NULL DEFAULT '{}',
            reasoning        TEXT,
            output_action    JSONB        NOT NULL DEFAULT '{}',
            constraints_check JSONB       NOT NULL DEFAULT '{}',
            confidence       FLOAT        NOT NULL DEFAULT 0.0,
            execution_ms     INTEGER,
            inference_layer  VARCHAR(20),
            model_id         VARCHAR(100),
            plan_id          VARCHAR(100),
            decided_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted       BOOLEAN      NOT NULL DEFAULT FALSE
        )
    """)

    # RLS — 与其他表保持一致，使用 NULLIF 防止 NULL 绕过
    op.execute("ALTER TABLE agent_decision_logs ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY agent_decision_logs_rls ON agent_decision_logs
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)

    # 索引：按租户 + agent + 时间倒序查询（最常见访问模式）
    # Ensure new columns exist (table may have been created by an earlier migration)
    op.execute("""
        ALTER TABLE agent_decision_logs
            ADD COLUMN IF NOT EXISTS plan_id     VARCHAR(100),
            ADD COLUMN IF NOT EXISTS is_deleted  BOOLEAN NOT NULL DEFAULT FALSE
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_decision_logs_tenant_agent_time
            ON agent_decision_logs(tenant_id, agent_id, decided_at DESC)
            WHERE is_deleted = false
    """)

    # 索引：按 plan_id 关联查询
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_decision_logs_plan_id
            ON agent_decision_logs(plan_id)
            WHERE plan_id IS NOT NULL AND is_deleted = false
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_decision_logs CASCADE")
