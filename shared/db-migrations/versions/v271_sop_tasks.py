"""v271 — sop_tasks + sop_task_instances（Phase S1: SOP时间轴引擎）

新建两张表：
  - sop_tasks: SOP任务定义（模板级，绑定时段）
  - sop_task_instances: SOP任务实例（门店级执行记录）

Revision ID: v271_sop_tasks
Revises: v270_sop_templates
Create Date: 2026-04-23
"""

from alembic import op

revision = "v271_sop_tasks"
down_revision = "v270_sop_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── sop_tasks ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS sop_tasks (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            template_id     UUID NOT NULL REFERENCES sop_templates(id),
            slot_id         UUID NOT NULL REFERENCES sop_time_slots(id),
            task_code       TEXT NOT NULL,
            task_name       TEXT NOT NULL,
            task_type       TEXT NOT NULL,
            target_role     TEXT NOT NULL,
            priority        TEXT DEFAULT 'normal',
            duration_min    INT,
            instructions    TEXT,
            checklist_items JSONB,
            condition_logic JSONB,
            auto_complete   JSONB,
            data_source     TEXT,
            sort_order      INT NOT NULL,
            is_active       BOOLEAN DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN DEFAULT FALSE
        )
    """)

    # 索引
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sop_tasks_template_slot
            ON sop_tasks (template_id, slot_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sop_tasks_target_role
            ON sop_tasks (target_role)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sop_tasks_task_code
            ON sop_tasks (task_code)
    """)

    # RLS
    op.execute("ALTER TABLE sop_tasks ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS sop_tasks_tenant ON sop_tasks")
    op.execute("""
        CREATE POLICY sop_tasks_tenant ON sop_tasks
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)

    # 注释
    op.execute("""
        COMMENT ON TABLE sop_tasks IS
            'Phase S1: SOP任务定义 — 模板级，绑定时段和角色';
        COMMENT ON COLUMN sop_tasks.task_type IS
            '任务类型：checklist / inspection / report / action';
        COMMENT ON COLUMN sop_tasks.target_role IS
            '目标角色：store_manager / kitchen_lead / floor_lead / cashier / all';
        COMMENT ON COLUMN sop_tasks.priority IS
            '优先级：critical / high / normal / low';
        COMMENT ON COLUMN sop_tasks.checklist_items IS
            '检查项列表 JSON，如 [{"item": "检查冰箱温度", "required": true}]';
        COMMENT ON COLUMN sop_tasks.condition_logic IS
            '条件逻辑 JSON，定义任务触发条件';
        COMMENT ON COLUMN sop_tasks.auto_complete IS
            '自动完成规则 JSON，如 {"source": "pos_data", "condition": "revenue > 0"}';
    """)

    # ── sop_task_instances ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS sop_task_instances (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            store_id        UUID NOT NULL,
            task_id         UUID NOT NULL REFERENCES sop_tasks(id),
            instance_date   DATE NOT NULL,
            slot_code       TEXT NOT NULL,
            assignee_id     UUID,
            target_role     TEXT NOT NULL,
            status          TEXT DEFAULT 'pending',
            started_at      TIMESTAMPTZ,
            completed_at    TIMESTAMPTZ,
            due_at          TIMESTAMPTZ NOT NULL,
            result          JSONB,
            compliance      TEXT,
            ai_suggestion   TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN DEFAULT FALSE
        )
    """)

    # 索引
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sop_task_instances_store_date
            ON sop_task_instances (store_id, instance_date)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sop_task_instances_status
            ON sop_task_instances (status)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sop_task_instances_assignee
            ON sop_task_instances (assignee_id)
    """)

    # 唯一约束（软删除友好）
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_sop_task_instances_store_task_date
            ON sop_task_instances (tenant_id, store_id, task_id, instance_date)
            WHERE NOT is_deleted
    """)

    # RLS
    op.execute("ALTER TABLE sop_task_instances ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS sop_task_instances_tenant ON sop_task_instances")
    op.execute("""
        CREATE POLICY sop_task_instances_tenant ON sop_task_instances
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)

    # 注释
    op.execute("""
        COMMENT ON TABLE sop_task_instances IS
            'Phase S1: SOP任务实例 — 门店级每日执行记录';
        COMMENT ON COLUMN sop_task_instances.status IS
            '状态：pending / in_progress / completed / overdue / skipped / auto_completed';
        COMMENT ON COLUMN sop_task_instances.compliance IS
            '合规结果：pass / fail / warning';
        COMMENT ON COLUMN sop_task_instances.ai_suggestion IS
            'Agent生成的智能建议';
    """)


def downgrade() -> None:
    # sop_task_instances
    op.execute("DROP POLICY IF EXISTS sop_task_instances_tenant ON sop_task_instances")
    op.execute("ALTER TABLE IF EXISTS sop_task_instances DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS uq_sop_task_instances_store_task_date")
    op.execute("DROP INDEX IF EXISTS idx_sop_task_instances_assignee")
    op.execute("DROP INDEX IF EXISTS idx_sop_task_instances_status")
    op.execute("DROP INDEX IF EXISTS idx_sop_task_instances_store_date")
    op.execute("DROP TABLE IF EXISTS sop_task_instances")

    # sop_tasks
    op.execute("DROP POLICY IF EXISTS sop_tasks_tenant ON sop_tasks")
    op.execute("ALTER TABLE IF EXISTS sop_tasks DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS idx_sop_tasks_task_code")
    op.execute("DROP INDEX IF EXISTS idx_sop_tasks_target_role")
    op.execute("DROP INDEX IF EXISTS idx_sop_tasks_template_slot")
    op.execute("DROP TABLE IF EXISTS sop_tasks")
