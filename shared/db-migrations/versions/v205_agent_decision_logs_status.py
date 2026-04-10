"""v205 — agent_decision_logs 补充 status 和 action 列

为 agent_hub_routes.py 的行动队列功能提供支持：
- status: 行动状态（pending_confirm / confirmed / dismissed / handling / resolved）
- action: 行动描述摘要（冗余字段，便于前端列表展示）

Revision ID: v205
Revises: v204
Create Date: 2026-04-07
"""

from alembic import op

revision = "v205"
down_revision = "v204"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE agent_decision_logs
            ADD COLUMN IF NOT EXISTS status VARCHAR(50)  NOT NULL DEFAULT 'pending_confirm',
            ADD COLUMN IF NOT EXISTS action VARCHAR(500)
    """)

    # status 枚举约束
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'chk_agent_decision_logs_status'
            ) THEN
                ALTER TABLE agent_decision_logs
                    ADD CONSTRAINT chk_agent_decision_logs_status
                    CHECK (status IN (
                        'pending_confirm', 'confirmed', 'dismissed',
                        'handling', 'resolved', 'error'
                    ));
            END IF;
        END $$
    """)

    # 索引：按状态查待处理行动（前端最常见访问）
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_decision_logs_status
            ON agent_decision_logs(tenant_id, status, created_at DESC)
            WHERE is_deleted = false
    """)

    # 将 output_action->>'summary' 或 decision_type 回填 action 字段
    op.execute("""
        UPDATE agent_decision_logs
        SET action = COALESCE(
            output_action->>'summary',
            output_action->>'description',
            decision_type
        )
        WHERE action IS NULL
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE agent_decision_logs DROP COLUMN IF EXISTS status")
    op.execute("ALTER TABLE agent_decision_logs DROP COLUMN IF EXISTS action")
