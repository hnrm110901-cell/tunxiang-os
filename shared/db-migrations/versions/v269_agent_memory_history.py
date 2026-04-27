"""v269 — agent_memory_history 记忆审计日志表（Phase M1）

新建 agent_memory_history — 记忆变更的不可变审计链。
跟踪所有记忆表（agent_memories / agent_episodes / agent_procedures）的
增删改衰合操作，用于问责和记忆进化分析。

设计要点：
  - 无 is_deleted：审计记录不可删除
  - event_type：ADD / UPDATE / DELETE / DECAY / MERGE
  - actor：agent / system / user（谁触发了变更）
  - old_value / new_value：变更前后快照

Revision ID: v269_mem_history
Revises: v268_procedures
Create Date: 2026-04-23
"""
from alembic import op

revision = "v269_mem_history"
down_revision = "v268_procedures"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_memory_history (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            memory_id       UUID NOT NULL,
            memory_table    TEXT NOT NULL,
            event_type      TEXT NOT NULL,
            old_value       JSONB,
            new_value       JSONB,
            reason          TEXT,
            actor           TEXT NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # 索引
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_memory_history_memory_id
            ON agent_memory_history (memory_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_memory_history_tenant_created
            ON agent_memory_history (tenant_id, created_at DESC)
    """)

    # RLS
    op.execute("ALTER TABLE agent_memory_history ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS agent_memory_history_tenant ON agent_memory_history")
    op.execute("""
        CREATE POLICY agent_memory_history_tenant ON agent_memory_history
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)

    # 注释
    op.execute("""
        COMMENT ON TABLE agent_memory_history IS
            'Phase M1: 记忆审计日志 — 不可变变更链，无 is_deleted';
        COMMENT ON COLUMN agent_memory_history.memory_table IS
            '来源表：agent_memories / agent_episodes / agent_procedures';
        COMMENT ON COLUMN agent_memory_history.event_type IS
            '变更类型：ADD / UPDATE / DELETE / DECAY / MERGE';
        COMMENT ON COLUMN agent_memory_history.actor IS
            '操作者：agent / system / user';
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS agent_memory_history_tenant ON agent_memory_history")
    op.execute("ALTER TABLE IF EXISTS agent_memory_history DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS idx_agent_memory_history_tenant_created")
    op.execute("DROP INDEX IF EXISTS idx_agent_memory_history_memory_id")
    op.execute("DROP TABLE IF EXISTS agent_memory_history")
