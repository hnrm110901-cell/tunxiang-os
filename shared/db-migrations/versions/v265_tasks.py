"""v265 — 任务引擎（10 类销售/服务任务统一模型）

对应规划：docs/reservation-roadmap-2026-q2.md §6 Sprint R1
依据路线图任务：
  任务引擎表 + API
  10 类：核餐 / 生日 / 纪念日 / 沉睡唤醒 / 新客 / 餐后回访 /
        宴会 6 阶段 / 商机 / 核餐 / 临时

本迁移只建表，不建业务路由。派单服务在 Sprint R2 补。

表清单：
  tasks — 统一任务表

RLS：tenant_id = app.tenant_id（对齐 CLAUDE.md §14）
事件：TaskEventType.DISPATCHED / COMPLETED / ESCALATED

Revision: v265
Revises: v264
Create Date: 2026-04-23
"""

from alembic import op

revision = "v265"
down_revision = "v264"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 1. 任务类型枚举（10 类任务）
    # ─────────────────────────────────────────────────────────────────
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE task_type_enum AS ENUM (
                'lead_follow_up',
                'banquet_stage',
                'dining_followup',
                'birthday',
                'anniversary',
                'dormant_recall',
                'new_customer',
                'confirm_arrival',
                'adhoc',
                'banquet_followup'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    # ─────────────────────────────────────────────────────────────────
    # 2. 任务状态枚举
    # ─────────────────────────────────────────────────────────────────
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE task_status_enum AS ENUM (
                'pending',
                'completed',
                'escalated',
                'cancelled'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    # ─────────────────────────────────────────────────────────────────
    # 3. tasks 表
    # ─────────────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            task_id                  UUID                  NOT NULL DEFAULT gen_random_uuid(),
            tenant_id                UUID                  NOT NULL,
            store_id                 UUID,
            task_type                task_type_enum        NOT NULL,
            assignee_employee_id     UUID                  NOT NULL,
            customer_id              UUID,
            due_at                   TIMESTAMPTZ           NOT NULL,
            status                   task_status_enum      NOT NULL DEFAULT 'pending',
            escalated_to_employee_id UUID,
            escalated_at             TIMESTAMPTZ,
            cancel_reason            VARCHAR(200),
            source_event_id          UUID,
            payload                  JSONB                 NOT NULL DEFAULT '{}',
            dispatched_at            TIMESTAMPTZ           NOT NULL DEFAULT NOW(),
            completed_at             TIMESTAMPTZ,
            created_at               TIMESTAMPTZ           NOT NULL DEFAULT NOW(),
            updated_at               TIMESTAMPTZ           NOT NULL DEFAULT NOW(),
            CONSTRAINT tasks_pkey PRIMARY KEY (task_id)
        )
        """
    )

    # 核心索引：按 (tenant_id, assignee, status, due_at) 查询销售员日清单
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tasks_assignee_status_due
            ON tasks (tenant_id, assignee_employee_id, status, due_at)
        """
    )
    # 索引：按客户维度查任务历史
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tasks_customer
            ON tasks (tenant_id, customer_id)
            WHERE customer_id IS NOT NULL
        """
    )
    # 索引：按任务类型聚合统计（10 类）
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tasks_type_status
            ON tasks (tenant_id, task_type, status)
        """
    )
    # 索引：逾期任务扫描（Agent 升级判断）
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tasks_due_pending
            ON tasks (tenant_id, due_at)
            WHERE status = 'pending'
        """
    )
    # payload GIN 索引（便于按业务键查询）
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tasks_payload_gin
            ON tasks USING GIN (payload)
        """
    )

    # ─────────────────────────────────────────────────────────────────
    # 4. RLS 多租户隔离
    # ─────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE tasks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tasks FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tasks_tenant_isolation ON tasks")
    op.execute(
        """
        CREATE POLICY tasks_tenant_isolation ON tasks
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID)
        """
    )

    # ─────────────────────────────────────────────────────────────────
    # 5. 注释
    # ─────────────────────────────────────────────────────────────────
    op.execute(
        "COMMENT ON TABLE tasks IS '统一任务引擎 — 10 类销售/服务任务（R1 新增）'"
    )
    op.execute(
        "COMMENT ON COLUMN tasks.task_type IS "
        "'10 类：lead_follow_up/banquet_stage/dining_followup/birthday/anniversary/"
        "dormant_recall/new_customer/confirm_arrival/adhoc/banquet_followup'"
    )
    op.execute(
        "COMMENT ON COLUMN tasks.escalated_to_employee_id IS "
        "'升级对象：销售未跟 → 店长 → 区经'"
    )
    op.execute(
        "COMMENT ON COLUMN tasks.payload IS "
        "'任务上下文 JSON：{reservation_id, banquet_lead_id, target_id, ...}'"
    )
    op.execute(
        "COMMENT ON COLUMN tasks.source_event_id IS '触发该任务的事件ID（可追溯因果链）'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tasks CASCADE")
    op.execute("DROP TYPE IF EXISTS task_status_enum")
    op.execute("DROP TYPE IF EXISTS task_type_enum")
