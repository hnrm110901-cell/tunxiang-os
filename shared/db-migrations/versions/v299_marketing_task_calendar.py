"""v299 — 营销任务日历

私域增长模块C：营销任务日历，支持一次性/周期/事件触发三种任务类型。

四张表：
  1. marketing_tasks — 营销任务（含内容模板+排期+审批）
  2. marketing_task_assignments — 任务分配（门店→员工→客户）
  3. marketing_task_executions — 执行记录（逐条发送状态跟踪）
  4. marketing_task_effects — 效果统计（按日/门店/员工聚合）

Revision ID: v299_mkt_task_cal
Revises: v298_audience_pack_worker
Create Date: 2026-04-24
"""
from alembic import op

revision = "v299_mkt_task_cal"
down_revision = "v298_audience_pack_worker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. marketing_tasks ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketing_tasks (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            task_name               VARCHAR(300) NOT NULL,
            description             TEXT,
            task_type               VARCHAR(30) NOT NULL DEFAULT 'one_time'
                                    CHECK (task_type IN ('one_time', 'recurring', 'event_triggered')),
            channel                 VARCHAR(30) NOT NULL DEFAULT 'private_chat'
                                    CHECK (channel IN ('private_chat', 'group_chat', 'moments')),
            audience_pack_id        UUID,
            audience_filter         JSONB,
            content                 JSONB NOT NULL DEFAULT '{}'::jsonb,
            schedule_at             TIMESTAMPTZ,
            schedule_end_at         TIMESTAMPTZ,
            recurrence_rule         JSONB,
            target_store_ids        JSONB NOT NULL DEFAULT '[]'::jsonb,
            target_employee_ids     JSONB NOT NULL DEFAULT '[]'::jsonb,
            priority                VARCHAR(10) NOT NULL DEFAULT 'normal'
                                    CHECK (priority IN ('urgent', 'high', 'normal', 'low')),
            status                  VARCHAR(20) NOT NULL DEFAULT 'draft'
                                    CHECK (status IN (
                                        'draft', 'scheduled', 'executing',
                                        'completed', 'paused', 'cancelled'
                                    )),
            total_target_count      INT NOT NULL DEFAULT 0,
            created_by              UUID NOT NULL,
            approved_by             UUID,
            approved_at             TIMESTAMPTZ,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mkt_tasks_tenant_status
            ON marketing_tasks (tenant_id, status, created_at DESC)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mkt_tasks_schedule
            ON marketing_tasks (tenant_id, schedule_at)
            WHERE is_deleted = false AND status = 'scheduled'
    """)

    op.execute("ALTER TABLE marketing_tasks ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS mkt_tasks_tenant_isolation ON marketing_tasks;
        CREATE POLICY mkt_tasks_tenant_isolation ON marketing_tasks
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ── 2. marketing_task_assignments ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketing_task_assignments (
            id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id                   UUID NOT NULL,
            task_id                     UUID NOT NULL REFERENCES marketing_tasks(id),
            store_id                    UUID NOT NULL,
            employee_id                 UUID,
            assigned_customer_count     INT NOT NULL DEFAULT 0,
            status                      VARCHAR(20) NOT NULL DEFAULT 'pending'
                                        CHECK (status IN (
                                            'pending', 'accepted', 'executing',
                                            'completed', 'skipped'
                                        )),
            started_at                  TIMESTAMPTZ,
            completed_at                TIMESTAMPTZ,
            created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted                  BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mkt_assignments_task
            ON marketing_task_assignments (task_id, status)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mkt_assignments_employee
            ON marketing_task_assignments (tenant_id, employee_id, status)
            WHERE is_deleted = false AND employee_id IS NOT NULL
    """)

    op.execute("ALTER TABLE marketing_task_assignments ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS mkt_assignments_tenant_isolation ON marketing_task_assignments;
        CREATE POLICY mkt_assignments_tenant_isolation ON marketing_task_assignments
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ── 3. marketing_task_executions ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketing_task_executions (
            id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id                   UUID NOT NULL,
            task_id                     UUID NOT NULL REFERENCES marketing_tasks(id),
            assignment_id               UUID REFERENCES marketing_task_assignments(id),
            store_id                    UUID,
            employee_id                 UUID,
            customer_id                 UUID,
            wecom_external_userid       VARCHAR(200),
            group_chat_id               VARCHAR(200),
            channel                     VARCHAR(30),
            send_status                 VARCHAR(20) NOT NULL DEFAULT 'pending'
                                        CHECK (send_status IN (
                                            'pending', 'sent', 'delivered',
                                            'read', 'failed'
                                        )),
            coupon_instance_id          UUID,
            failure_reason              TEXT,
            sent_at                     TIMESTAMPTZ,
            delivered_at                TIMESTAMPTZ,
            read_at                     TIMESTAMPTZ,
            created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted                  BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mkt_executions_task
            ON marketing_task_executions (task_id, send_status)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mkt_executions_customer
            ON marketing_task_executions (tenant_id, customer_id, created_at DESC)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE marketing_task_executions ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS mkt_executions_tenant_isolation ON marketing_task_executions;
        CREATE POLICY mkt_executions_tenant_isolation ON marketing_task_executions
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ── 4. marketing_task_effects ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS marketing_task_effects (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            task_id                 UUID NOT NULL REFERENCES marketing_tasks(id),
            store_id                UUID,
            employee_id             UUID,
            stat_date               DATE NOT NULL,
            total_sent              INT NOT NULL DEFAULT 0,
            delivered               INT NOT NULL DEFAULT 0,
            read                    INT NOT NULL DEFAULT 0,
            clicked                 INT NOT NULL DEFAULT 0,
            converted               INT NOT NULL DEFAULT 0,
            coupon_issued_count     INT NOT NULL DEFAULT 0,
            redeemed_count          INT NOT NULL DEFAULT 0,
            revenue_fen             BIGINT NOT NULL DEFAULT 0,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE,
            CONSTRAINT uq_mkt_task_effect
                UNIQUE (tenant_id, task_id, store_id, employee_id, stat_date)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mkt_effects_task
            ON marketing_task_effects (task_id, stat_date DESC)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE marketing_task_effects ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS mkt_effects_tenant_isolation ON marketing_task_effects;
        CREATE POLICY mkt_effects_tenant_isolation ON marketing_task_effects
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS marketing_task_effects CASCADE")
    op.execute("DROP TABLE IF EXISTS marketing_task_executions CASCADE")
    op.execute("DROP TABLE IF EXISTS marketing_task_assignments CASCADE")
    op.execute("DROP TABLE IF EXISTS marketing_tasks CASCADE")
