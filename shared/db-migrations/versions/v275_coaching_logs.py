"""v275 — sop_coaching_logs（Phase S3: AI运营教练）

新建表：
  - sop_coaching_logs: AI教练决策日志（晨会简报/高峰预警/复盘分析/闭店日报）

Revision ID: v275_coaching_logs
Revises: v274_sop_quick_actions
Create Date: 2026-04-23
"""

from alembic import op

revision = "v275_coaching_logs"
down_revision = "v274_sop_quick_actions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── sop_coaching_logs ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS sop_coaching_logs (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            store_id            UUID NOT NULL,
            user_id             UUID,
            coaching_type       TEXT NOT NULL,
            slot_code           TEXT NOT NULL,
            coaching_date       DATE NOT NULL,
            context_snapshot    JSONB NOT NULL DEFAULT '{}',
            memories_used       UUID[],
            recommendations     JSONB NOT NULL DEFAULT '{}',
            user_feedback       TEXT,
            feedback_at         TIMESTAMPTZ,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN DEFAULT FALSE
        )
    """)

    # 索引：(store_id, coaching_date) — 按门店+日期查询教练日志
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_coaching_logs_store_date
            ON sop_coaching_logs (store_id, coaching_date)
    """)

    # 索引：(coaching_type) — 按教练类型过滤
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_coaching_logs_type
            ON sop_coaching_logs (coaching_type)
    """)

    # RLS
    op.execute("ALTER TABLE sop_coaching_logs ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS sop_coaching_logs_tenant ON sop_coaching_logs")
    op.execute("""
        CREATE POLICY sop_coaching_logs_tenant ON sop_coaching_logs
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)

    # 注释
    op.execute("""
        COMMENT ON TABLE sop_coaching_logs IS
            'Phase S3: AI运营教练决策日志 — 记录每次教练推送的上下文和建议';
        COMMENT ON COLUMN sop_coaching_logs.coaching_type IS
            '教练类型：morning_brief / peak_alert / post_rush_review / closing_summary';
        COMMENT ON COLUMN sop_coaching_logs.slot_code IS
            '关联时段代码（如lunch_peak/dinner_peak/closing）';
        COMMENT ON COLUMN sop_coaching_logs.context_snapshot IS
            '当时的业务上下文快照（指标、基线等）';
        COMMENT ON COLUMN sop_coaching_logs.memories_used IS
            '本次教练使用的记忆ID列表';
        COMMENT ON COLUMN sop_coaching_logs.recommendations IS
            '教练生成的建议内容 JSON';
        COMMENT ON COLUMN sop_coaching_logs.user_feedback IS
            '用户反馈：helpful / not_helpful / ignored';
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS sop_coaching_logs_tenant ON sop_coaching_logs")
    op.execute("ALTER TABLE IF EXISTS sop_coaching_logs DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS idx_coaching_logs_type")
    op.execute("DROP INDEX IF EXISTS idx_coaching_logs_store_date")
    op.execute("DROP TABLE IF EXISTS sop_coaching_logs")
