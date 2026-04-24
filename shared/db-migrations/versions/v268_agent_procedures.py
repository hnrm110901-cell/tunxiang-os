"""v268 — agent_procedures 程序性记忆表（Phase M1）

新建 agent_procedures — Agent 的"肌肉记忆"，存储经验证有效的触发-动作规则。
当特定模式重复出现时，Agent 可直接执行对应 SOP，无需每次重新推理。

字段：
  procedure_name   — 程序名称（如"午高峰前备料提醒"）
  trigger_pattern  — 触发模式（如"workday && 10:00 && inventory < threshold"）
  trigger_config   — 触发条件详细配置（JSONB）
  action_template  — 动作模板（JSONB）
  success_rate     — 历史成功率
  execution_count  — 累计执行次数
  is_active        — 是否启用

Revision ID: v268_procedures
Revises: v267_episodes
Create Date: 2026-04-23
"""

from alembic import op

revision = "v268_procedures"
down_revision = "v267_episodes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_procedures (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            store_id        UUID,
            procedure_name  TEXT NOT NULL,
            trigger_pattern TEXT NOT NULL,
            trigger_config  JSONB NOT NULL,
            action_template JSONB NOT NULL,
            success_rate    FLOAT NOT NULL DEFAULT 0.0,
            execution_count INTEGER NOT NULL DEFAULT 0,
            last_executed   TIMESTAMPTZ,
            is_active       BOOLEAN NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    # 索引
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_procedures_tenant_store
            ON agent_procedures (tenant_id, store_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_procedures_trigger
            ON agent_procedures (trigger_pattern)
    """)

    # RLS
    op.execute("ALTER TABLE agent_procedures ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS agent_procedures_tenant ON agent_procedures")
    op.execute("""
        CREATE POLICY agent_procedures_tenant ON agent_procedures
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)

    # 注释
    op.execute("""
        COMMENT ON TABLE agent_procedures IS
            'Phase M1: Agent 程序性记忆 — 经验证有效的触发-动作规则';
        COMMENT ON COLUMN agent_procedures.store_id IS
            '门店范围，NULL 表示品牌级程序';
        COMMENT ON COLUMN agent_procedures.trigger_pattern IS
            '触发模式标识（用于快速匹配）';
        COMMENT ON COLUMN agent_procedures.trigger_config IS
            '触发条件详细配置 JSON';
        COMMENT ON COLUMN agent_procedures.action_template IS
            '动作模板 JSON（包含参数占位符）';
        COMMENT ON COLUMN agent_procedures.success_rate IS
            '历史成功率 0.0-1.0';
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS agent_procedures_tenant ON agent_procedures")
    op.execute("ALTER TABLE IF EXISTS agent_procedures DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS idx_agent_procedures_trigger")
    op.execute("DROP INDEX IF EXISTS idx_agent_procedures_tenant_store")
    op.execute("DROP TABLE IF EXISTS agent_procedures")
