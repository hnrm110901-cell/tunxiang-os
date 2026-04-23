"""v267 — agent_episodes 事件片段表（Phase M1）

新建 agent_episodes — 记录门店运营中的关键事件片段（异常/决策/事故/成功），
作为 Agent 的"情景记忆"，用于经验学习和类比推理。

字段：
  episode_type     — anomaly / decision / incident / success
  time_slot        — morning_prep / lunch_peak / afternoon_lull / dinner_peak / closing
  context          — 事件发生时的完整上下文（JSONB）
  action_taken     — Agent 或人采取的行动
  outcome          — 结果（JSONB）
  lesson           — 提炼的经验教训
  related_memories — 关联的记忆 ID 数组

Revision ID: v267_episodes
Revises: v266_mem_evo
Create Date: 2026-04-23
"""
from alembic import op

revision = "v267_episodes"
down_revision = "v266_mem_evo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_episodes (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            store_id        UUID NOT NULL,
            episode_type    TEXT NOT NULL,
            episode_date    DATE NOT NULL,
            time_slot       TEXT,
            context         JSONB NOT NULL,
            action_taken    JSONB,
            outcome         JSONB,
            lesson          TEXT,
            related_memories UUID[],
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    # 索引
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_episodes_tenant_store_date
            ON agent_episodes (tenant_id, store_id, episode_date)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_episodes_type
            ON agent_episodes (episode_type)
    """)

    # RLS
    op.execute("ALTER TABLE agent_episodes ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS agent_episodes_tenant ON agent_episodes")
    op.execute("""
        CREATE POLICY agent_episodes_tenant ON agent_episodes
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)

    # 列注释
    op.execute("""
        COMMENT ON TABLE agent_episodes IS
            'Phase M1: Agent 情景记忆 — 门店运营关键事件片段';
        COMMENT ON COLUMN agent_episodes.episode_type IS
            '事件类型：anomaly / decision / incident / success';
        COMMENT ON COLUMN agent_episodes.time_slot IS
            '时段：morning_prep / lunch_peak / afternoon_lull / dinner_peak / closing';
        COMMENT ON COLUMN agent_episodes.related_memories IS
            '关联的 agent_memories ID 数组';
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS agent_episodes_tenant ON agent_episodes")
    op.execute("ALTER TABLE IF EXISTS agent_episodes DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS idx_agent_episodes_type")
    op.execute("DROP INDEX IF EXISTS idx_agent_episodes_tenant_store_date")
    op.execute("DROP TABLE IF EXISTS agent_episodes")
