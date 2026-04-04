"""通用审批流引擎

新增表：
  approval_workflow_templates  — 审批流模板（按业务类型+条件匹配）
  approval_instances           — 审批实例（每次发起审批创建一条）
  approval_step_records        — 审批步骤操作记录（审批人每次动作一条）

审批场景：
  - 采购审批（purchase_order）：金额>1000元需主管，>5000元需总监
  - 折扣审批（discount）：折扣率>20%需店长，>30%需总监
  - 菜单变更（menu_change）：价格调整/新品上线
  - 人事审批（hr_request）：换班/请假
  - 报销审批（expense）：费用报销

RLS 策略：
  全部使用 v006+ 标准安全模式（4操作 + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v059
Revises: v047
Create Date: 2026-03-31
"""

from alembic import op

revision = "v059"
down_revision = "v047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 1. approval_workflow_templates — 审批流模板
    #    总部配置，按 business_type + context 条件匹配
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS approval_workflow_templates (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            name            VARCHAR(100) NOT NULL,
            business_type   VARCHAR(50)  NOT NULL
                CHECK (business_type IN (
                    'purchase_order',   -- 采购审批
                    'discount',         -- 折扣审批
                    'menu_change',      -- 菜单变更（价格/上架）
                    'hr_request',       -- 人事审批（换班/请假）
                    'expense'           -- 报销审批
                )),
            -- steps JSONB 格式示例：
            -- [
            --   {"step": 1, "approver_role": "store_manager", "timeout_hours": 24},
            --   {"step": 2, "approver_role": "area_director", "timeout_hours": 48,
            --    "condition": {"field": "amount", "op": ">", "value": 5000}}
            -- ]
            steps           JSONB        NOT NULL DEFAULT '[]',
            -- conditions 定义模板何时被选中的上下文条件（JSONB）
            -- 示例：{"amount": {"op": ">", "value": 1000}}
            -- 为空则表示通用模板（最低优先级）
            conditions      JSONB        NOT NULL DEFAULT '{}',
            is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN      NOT NULL DEFAULT FALSE
        );

        COMMENT ON TABLE approval_workflow_templates IS
            '审批流模板：总部配置，按业务类型和上下文条件匹配，支持多步审批和条件路由';
        COMMENT ON COLUMN approval_workflow_templates.steps IS
            '审批步骤列表 JSONB，每步含 step/approver_role/timeout_hours/condition（可选）';
        COMMENT ON COLUMN approval_workflow_templates.conditions IS
            '模板匹配条件 JSONB，用于从多个模板中选出最合适的一个';

        CREATE INDEX IF NOT EXISTS ix_approval_workflow_templates_tenant_type
            ON approval_workflow_templates (tenant_id, business_type)
            WHERE is_deleted = FALSE AND is_active = TRUE;
    """)

    # RLS: approval_workflow_templates
    op.execute("""
        ALTER TABLE approval_workflow_templates ENABLE ROW LEVEL SECURITY;
        ALTER TABLE approval_workflow_templates FORCE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS approval_workflow_templates_tenant_isolation ON approval_workflow_templates;
        CREATE POLICY approval_workflow_templates_tenant_isolation
            ON approval_workflow_templates
            AS PERMISSIVE FOR ALL
            USING (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            )
            WITH CHECK (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
    """)

    # ─────────────────────────────────────────────────────────────────
    # 2. approval_instances — 审批实例
    #    每次发起审批创建一条记录，关联模板和业务单据
    # ─────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE approval_instances ADD COLUMN IF NOT EXISTS context_data JSONB DEFAULT '{}'")
    op.execute("ALTER TABLE approval_instances ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ")
    op.execute("ALTER TABLE approval_instances ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE")
    op.execute("""
        CREATE TABLE IF NOT EXISTS approval_instances (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            template_id     UUID        REFERENCES approval_workflow_templates(id),
            business_type   VARCHAR(50)  NOT NULL,
            business_id     VARCHAR(200) NOT NULL,   -- 关联业务单据ID（字符串兼容各业务）
            title           VARCHAR(200) NOT NULL,
            initiator_id    UUID        NOT NULL,    -- 发起人员工ID
            current_step    INT         NOT NULL DEFAULT 1,
            status          VARCHAR(20)  NOT NULL DEFAULT 'pending'
                CHECK (status IN (
                    'pending',      -- 审批中
                    'approved',     -- 已通过
                    'rejected',     -- 已拒绝
                    'cancelled',    -- 已撤回
                    'timeout'       -- 已超时
                )),
            -- context_data 存储发起审批时的业务上下文，用于条件路由
            -- 示例：{"amount": 6500, "discount_rate": 0.25, "store_id": "xxx"}
            context_data    JSONB        NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            completed_at    TIMESTAMPTZ,
            is_deleted      BOOLEAN      NOT NULL DEFAULT FALSE
        );

        COMMENT ON TABLE approval_instances IS
            '审批实例：每次发起审批一条记录，状态机流转 pending→approved/rejected/cancelled/timeout';
        COMMENT ON COLUMN approval_instances.business_id IS
            '关联业务单据ID，采购单/折扣申请/菜单变更记录等的主键';
        COMMENT ON COLUMN approval_instances.context_data IS
            '发起时的业务上下文 JSONB，用于条件路由和审批详情展示';

        CREATE INDEX IF NOT EXISTS ix_approval_instances_tenant_status
            ON approval_instances (tenant_id, status)
            WHERE is_deleted = FALSE;

        CREATE INDEX IF NOT EXISTS ix_approval_instances_initiator
            ON approval_instances (tenant_id, initiator_id)
            WHERE is_deleted = FALSE;

        CREATE INDEX IF NOT EXISTS ix_approval_instances_business
            ON approval_instances (tenant_id, business_type, business_id)
            WHERE is_deleted = FALSE;

        CREATE INDEX IF NOT EXISTS ix_approval_instances_template
            ON approval_instances (tenant_id, template_id)
            WHERE is_deleted = FALSE;
    """)

    # RLS: approval_instances
    op.execute("""
        ALTER TABLE approval_instances ENABLE ROW LEVEL SECURITY;
        ALTER TABLE approval_instances FORCE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS approval_instances_tenant_isolation ON approval_instances;
        CREATE POLICY approval_instances_tenant_isolation
            ON approval_instances
            AS PERMISSIVE FOR ALL
            USING (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            )
            WITH CHECK (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
    """)

    # ─────────────────────────────────────────────────────────────────
    # 3. approval_step_records — 审批步骤操作记录
    #    审批人每次动作（通过/拒绝/转交）记录一条
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS approval_step_records (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            instance_id     UUID        NOT NULL REFERENCES approval_instances(id),
            step            INT         NOT NULL,
            approver_id     UUID        NOT NULL,    -- 操作人员工ID
            action          VARCHAR(20)  NOT NULL
                CHECK (action IN (
                    'approve',      -- 通过
                    'reject',       -- 拒绝
                    'forward'       -- 转交
                )),
            comment         TEXT,                    -- 审批意见
            acted_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );

        COMMENT ON TABLE approval_step_records IS
            '审批步骤操作记录：审批人每次动作一条，构成完整审批时间线';
        COMMENT ON COLUMN approval_step_records.action IS
            'approve=通过, reject=拒绝, forward=转交他人';

        CREATE INDEX IF NOT EXISTS ix_approval_step_records_instance
            ON approval_step_records (instance_id);

        CREATE INDEX IF NOT EXISTS ix_approval_step_records_tenant_approver
            ON approval_step_records (tenant_id, approver_id);

        CREATE INDEX IF NOT EXISTS ix_approval_step_records_tenant_acted
            ON approval_step_records (tenant_id, acted_at DESC);
    """)

    # RLS: approval_step_records
    op.execute("""
        ALTER TABLE approval_step_records ENABLE ROW LEVEL SECURITY;
        ALTER TABLE approval_step_records FORCE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS approval_step_records_tenant_isolation ON approval_step_records;
        CREATE POLICY approval_step_records_tenant_isolation
            ON approval_step_records
            AS PERMISSIVE FOR ALL
            USING (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            )
            WITH CHECK (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS approval_step_records CASCADE;")
    op.execute("DROP TABLE IF EXISTS approval_instances CASCADE;")
    op.execute("DROP TABLE IF EXISTS approval_workflow_templates CASCADE;")
