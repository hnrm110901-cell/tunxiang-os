"""v277 — memory_feedback_signals（Phase S4: 记忆进化闭环）

新建表：
  - memory_feedback_signals: 用户行为反馈信号采集表（驱动记忆进化的原始数据）

信号类型: click / dismiss / dwell / feedback / override
来源: im_card / dashboard / coaching / sop_task

Revision ID: v277_memory_feedback_signals
Revises: v276_store_baselines
Create Date: 2026-04-23
"""

from alembic import op

revision = "v277_memory_feedback_signals"
down_revision = "v276_store_baselines"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── memory_feedback_signals ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS memory_feedback_signals (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            store_id        UUID NOT NULL,
            user_id         UUID NOT NULL,
            signal_type     TEXT NOT NULL,
            source          TEXT NOT NULL,
            source_id       UUID,
            signal_data     JSONB NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # 索引：(store_id, user_id, created_at DESC) — 按门店+用户+时间查询
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_feedback_signals_store_user_time
            ON memory_feedback_signals (store_id, user_id, created_at DESC)
    """)

    # 索引：(signal_type) — 按信号类型过滤
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_feedback_signals_type
            ON memory_feedback_signals (signal_type)
    """)

    # 索引：(source, source_id) — 按来源关联查询
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_feedback_signals_source
            ON memory_feedback_signals (source, source_id)
    """)

    # RLS
    op.execute("ALTER TABLE memory_feedback_signals ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS memory_feedback_signals_tenant ON memory_feedback_signals")
    op.execute("""
        CREATE POLICY memory_feedback_signals_tenant ON memory_feedback_signals
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)

    # 注释
    op.execute("""
        COMMENT ON TABLE memory_feedback_signals IS
            'Phase S4: 用户行为反馈信号采集 — 驱动记忆进化闭环的原始数据';
        COMMENT ON COLUMN memory_feedback_signals.signal_type IS
            '信号类型：click / dismiss / dwell / feedback / override';
        COMMENT ON COLUMN memory_feedback_signals.source IS
            '信号来源：im_card / dashboard / coaching / sop_task';
        COMMENT ON COLUMN memory_feedback_signals.source_id IS
            '关联的卡片/任务/建议ID（可为空）';
        COMMENT ON COLUMN memory_feedback_signals.signal_data IS
            '信号详情 JSON，如 {"action": "expanded_cost_detail", "duration_sec": 45}';
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS memory_feedback_signals_tenant ON memory_feedback_signals")
    op.execute("ALTER TABLE IF EXISTS memory_feedback_signals DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS idx_feedback_signals_source")
    op.execute("DROP INDEX IF EXISTS idx_feedback_signals_type")
    op.execute("DROP INDEX IF EXISTS idx_feedback_signals_store_user_time")
    op.execute("DROP TABLE IF EXISTS memory_feedback_signals")
