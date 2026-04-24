"""v272 — sop_corrective_actions + sop_store_configs（Phase S1: SOP时间轴引擎）

新建两张表：
  - sop_corrective_actions: 纠正动作链（任务不合规时的跟踪闭环）
  - sop_store_configs: 门店SOP配置（门店绑定哪个SOP模板）

Revision ID: v272_sop_corrective
Revises: v271_sop_tasks
Create Date: 2026-04-23
"""

from alembic import op

revision = "v272_sop_corrective"
down_revision = "v271_sop_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── sop_corrective_actions ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS sop_corrective_actions (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            store_id            UUID NOT NULL,
            source_instance_id  UUID NOT NULL REFERENCES sop_task_instances(id),
            action_type         TEXT NOT NULL,
            severity            TEXT NOT NULL,
            title               TEXT NOT NULL,
            description         TEXT NOT NULL,
            assignee_id         UUID NOT NULL,
            due_at              TIMESTAMPTZ NOT NULL,
            status              TEXT DEFAULT 'open',
            resolution          JSONB,
            verified_by         UUID,
            verified_at         TIMESTAMPTZ,
            escalated_to        UUID,
            escalated_at        TIMESTAMPTZ,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN DEFAULT FALSE
        )
    """)

    # 索引
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sop_corrective_actions_store_status
            ON sop_corrective_actions (store_id, status)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sop_corrective_actions_source
            ON sop_corrective_actions (source_instance_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sop_corrective_actions_assignee
            ON sop_corrective_actions (assignee_id)
    """)

    # RLS
    op.execute("ALTER TABLE sop_corrective_actions ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS sop_corrective_actions_tenant ON sop_corrective_actions")
    op.execute("""
        CREATE POLICY sop_corrective_actions_tenant ON sop_corrective_actions
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)

    # 注释
    op.execute("""
        COMMENT ON TABLE sop_corrective_actions IS
            'Phase S1: SOP纠正动作链 — 任务不合规时的跟踪闭环';
        COMMENT ON COLUMN sop_corrective_actions.action_type IS
            '动作类型：immediate / follow_up / escalation';
        COMMENT ON COLUMN sop_corrective_actions.severity IS
            '严重程度：critical / warning / info';
        COMMENT ON COLUMN sop_corrective_actions.status IS
            '状态：open / in_progress / resolved / verified / escalated';
    """)

    # ── sop_store_configs ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS sop_store_configs (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            store_id            UUID NOT NULL,
            template_id         UUID NOT NULL REFERENCES sop_templates(id),
            timezone            TEXT DEFAULT 'Asia/Shanghai',
            custom_overrides    JSONB DEFAULT '{}',
            is_active           BOOLEAN DEFAULT TRUE,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN DEFAULT FALSE
        )
    """)

    # 唯一约束（软删除友好）
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_sop_store_configs_tenant_store
            ON sop_store_configs (tenant_id, store_id)
            WHERE NOT is_deleted
    """)

    # RLS
    op.execute("ALTER TABLE sop_store_configs ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS sop_store_configs_tenant ON sop_store_configs")
    op.execute("""
        CREATE POLICY sop_store_configs_tenant ON sop_store_configs
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)

    # 注释
    op.execute("""
        COMMENT ON TABLE sop_store_configs IS
            'Phase S1: 门店SOP配置 — 门店绑定SOP模板 + 时区 + 自定义覆盖';
        COMMENT ON COLUMN sop_store_configs.custom_overrides IS
            '自定义覆盖 JSON，可覆盖模板中的时段/任务配置';
    """)


def downgrade() -> None:
    # sop_store_configs
    op.execute("DROP POLICY IF EXISTS sop_store_configs_tenant ON sop_store_configs")
    op.execute("ALTER TABLE IF EXISTS sop_store_configs DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS uq_sop_store_configs_tenant_store")
    op.execute("DROP TABLE IF EXISTS sop_store_configs")

    # sop_corrective_actions
    op.execute("DROP POLICY IF EXISTS sop_corrective_actions_tenant ON sop_corrective_actions")
    op.execute("ALTER TABLE IF EXISTS sop_corrective_actions DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS idx_sop_corrective_actions_assignee")
    op.execute("DROP INDEX IF EXISTS idx_sop_corrective_actions_source")
    op.execute("DROP INDEX IF EXISTS idx_sop_corrective_actions_store_status")
    op.execute("DROP TABLE IF EXISTS sop_corrective_actions")
