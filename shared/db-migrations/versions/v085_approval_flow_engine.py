"""可配置审批流引擎 — 替换空壳实现

新增 4 张表（独立节点设计，支持多人审批策略 + 角色等级匹配）：
  approval_flow_templates   — 审批流模板定义
  approval_flow_nodes       — 审批节点（每个模板可有多个节点，独立行存储）
  approval_instances        — 审批单实例（每次发起审批一条记录）
  approval_node_instances   — 每个节点的审批操作记录（多人审批时一人一行）

设计要点：
  - approval_flow_nodes 独立行存储，支持 role_level / specific_role /
    specific_person / auto 四种节点类型
  - approve_type='any_one' 任一通过即可；'all_must' 全部通过才进入下一节点
  - trigger_conditions JSONB：模板级别触发条件，不满足则无需审批（自动通过）
  - auto_approve_condition JSONB：节点级别自动审批条件
  - timeout_action：超时后自动审批 / 自动拒绝 / 升级处理

与现有表的关系：
  - 与 v059 的 approval_workflow_templates / approval_instances /
    approval_step_records 并存，不删除旧表（保持向后兼容）
  - approval_instances 与 v059 同名，本迁移添加新列（summary, store_id,
    current_node_order, completed_at）

RLS：全部使用 v006+ 标准安全模式（4 操作 + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v061
Revises: v059
Create Date: 2026-03-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = 'v085'
down_revision = 'v084'
branch_labels = None
depends_on = None

_RLS_COND = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID"
)


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 1. approval_flow_templates — 审批流模板定义
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS approval_flow_templates (
            id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID         NOT NULL,
            template_name    VARCHAR(100) NOT NULL,
            business_type    VARCHAR(30)  NOT NULL
                CHECK (business_type IN (
                    'leave',         -- 请假审批
                    'purchase',      -- 采购审批
                    'discount',      -- 折扣审批
                    'price_change',  -- 价格调整审批
                    'refund',        -- 退款审批
                    'expense',       -- 报销审批
                    'custom'         -- 自定义业务
                )),
            -- 触发条件 JSONB：满足此条件才需要审批，否则自动通过
            -- 示例：{"amount": {"op": ">=", "value": 100000}}  金额>=1000元才触发
            -- 为空 {} 表示无条件触发（始终需要审批）
            trigger_conditions JSONB      NOT NULL DEFAULT '{}',
            is_active         BOOLEAN      NOT NULL DEFAULT TRUE,
            created_by        UUID,
            created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );

        COMMENT ON TABLE approval_flow_templates IS
            '审批流模板：每个业务类型可配置多个模板，通过 trigger_conditions 决定何时触发';
        COMMENT ON COLUMN approval_flow_templates.trigger_conditions IS
            '触发条件 JSONB，{field: {op, value}}，为空则始终触发审批';

        CREATE INDEX IF NOT EXISTS ix_aft_tenant_type_active
            ON approval_flow_templates (tenant_id, business_type)
            WHERE is_active = TRUE;
    """)

    # RLS
    op.execute("ALTER TABLE approval_flow_templates ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE approval_flow_templates FORCE ROW LEVEL SECURITY;")
    for op_name in ("select", "insert", "update", "delete"):
        check = f"WITH CHECK ({_RLS_COND})" if op_name in ("insert", "update") else ""
        op.execute(f"""
            CREATE POLICY rls_aft_{op_name}
                ON approval_flow_templates
                FOR {op_name.upper()}
                USING ({_RLS_COND})
                {check};
        """)

    # ─────────────────────────────────────────────────────────────────
    # 2. approval_flow_nodes — 审批节点
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS approval_flow_nodes (
            id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID        NOT NULL,
            template_id             UUID        NOT NULL
                REFERENCES approval_flow_templates(id) ON DELETE CASCADE,
            node_order              INTEGER      NOT NULL CHECK (node_order >= 1),
            node_name               VARCHAR(100) NOT NULL,
            -- 节点类型
            node_type               VARCHAR(20)  NOT NULL
                CHECK (node_type IN (
                    'role_level',      -- 角色等级 >= N 的员工（store 范围内）
                    'specific_role',   -- 指定角色 ID 的员工
                    'specific_person', -- 指定员工
                    'auto'             -- 自动审批（由 auto_approve_condition 控制）
                )),
            -- 审批人配置（按 node_type 三选一）
            approver_role_level     INTEGER,     -- node_type='role_level'：角色等级 >= 该值
            approver_role_id        UUID,        -- node_type='specific_role'：角色配置 ID
            approver_employee_id    UUID,        -- node_type='specific_person'：员工 ID

            -- 多人审批策略
            approve_type            VARCHAR(10)  NOT NULL DEFAULT 'any_one'
                CHECK (approve_type IN (
                    'any_one',   -- 任意一人通过即可进入下一节点
                    'all_must'   -- 必须全部通过才进入下一节点
                )),

            -- 节点自动审批条件 JSONB
            -- 示例：{"amount": {"op": "<", "value": 50000}}  金额<500元自动通过
            auto_approve_condition  JSONB,

            -- 超时配置
            timeout_hours           INTEGER,      -- NULL 表示不超时
            timeout_action          VARCHAR(20)
                CHECK (timeout_action IN ('auto_approve', 'auto_reject', 'escalate', NULL)),

            created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

            -- 同一模板内节点序号唯一
            CONSTRAINT uq_afn_template_order UNIQUE (template_id, node_order)
        );

        COMMENT ON TABLE approval_flow_nodes IS
            '审批节点：每个模板可有多个节点，按 node_order 顺序执行';
        COMMENT ON COLUMN approval_flow_nodes.approve_type IS
            'any_one=任一审批人通过即可；all_must=所有审批人都需通过';
        COMMENT ON COLUMN approval_flow_nodes.auto_approve_condition IS
            '节点级自动审批条件，满足时跳过人工审批直接通过';

        CREATE INDEX IF NOT EXISTS ix_afn_template_order
            ON approval_flow_nodes (template_id, node_order);

        CREATE INDEX IF NOT EXISTS ix_afn_tenant_id
            ON approval_flow_nodes (tenant_id);
    """)

    # RLS
    op.execute("ALTER TABLE approval_flow_nodes ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE approval_flow_nodes FORCE ROW LEVEL SECURITY;")
    for op_name in ("select", "insert", "update", "delete"):
        check = f"WITH CHECK ({_RLS_COND})" if op_name in ("insert", "update") else ""
        op.execute(f"""
            CREATE POLICY rls_afn_{op_name}
                ON approval_flow_nodes
                FOR {op_name.upper()}
                USING ({_RLS_COND})
                {check};
        """)

    # ─────────────────────────────────────────────────────────────────
    # 3. approval_instances — 审批单实例（重用 v059 同名表，扩展字段）
    #    注意：v059 已建了 approval_instances，这里 ADD COLUMN 扩展
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        -- 新增字段（幂等 ADD COLUMN IF NOT EXISTS）
        ALTER TABLE approval_instances
            ADD COLUMN IF NOT EXISTS flow_template_id    UUID
                REFERENCES approval_flow_templates(id),
            ADD COLUMN IF NOT EXISTS store_id            UUID,
            ADD COLUMN IF NOT EXISTS current_node_order  INTEGER DEFAULT 1,
            ADD COLUMN IF NOT EXISTS summary             JSONB   DEFAULT '{}',
            ADD COLUMN IF NOT EXISTS completed_at        TIMESTAMPTZ;

        COMMENT ON COLUMN approval_instances.flow_template_id IS
            '关联的新式审批流模板 ID（approval_flow_templates），NULL 表示使用旧式工作流';
        COMMENT ON COLUMN approval_instances.store_id IS
            '发起审批的门店 ID，用于查找门店范围内的审批人';
        COMMENT ON COLUMN approval_instances.current_node_order IS
            '当前所在节点序号（approval_flow_nodes.node_order）';
        COMMENT ON COLUMN approval_instances.summary IS
            '业务摘要 JSONB，冗余存储减少关联查询，如 {amount, days, item_name}';

        CREATE INDEX IF NOT EXISTS ix_ai_flow_template
            ON approval_instances (tenant_id, flow_template_id)
            WHERE flow_template_id IS NOT NULL AND is_deleted = FALSE;

        CREATE INDEX IF NOT EXISTS ix_ai_store_status
            ON approval_instances (tenant_id, store_id, status)
            WHERE is_deleted = FALSE;
    """)

    # ─────────────────────────────────────────────────────────────────
    # 4. approval_node_instances — 每个节点的审批操作记录
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS approval_node_instances (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            instance_id     UUID        NOT NULL
                REFERENCES approval_instances(id) ON DELETE CASCADE,
            node_order      INTEGER      NOT NULL CHECK (node_order >= 1),
            approver_id     UUID        NOT NULL,   -- 实际审批人员工 ID
            status          VARCHAR(20)  NOT NULL DEFAULT 'pending'
                CHECK (status IN (
                    'pending',   -- 待审批
                    'approved',  -- 已同意
                    'rejected',  -- 已拒绝
                    'skipped',   -- 已跳过（自动审批或 any_one 已被他人通过）
                    'timeout'    -- 已超时
                )),
            comment         TEXT,
            decided_at      TIMESTAMPTZ,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );

        COMMENT ON TABLE approval_node_instances IS
            '节点审批记录：多人审批时每人一行，记录每个人的审批意见和结果';

        CREATE INDEX IF NOT EXISTS ix_ani_instance_node
            ON approval_node_instances (instance_id, node_order);

        CREATE INDEX IF NOT EXISTS ix_ani_tenant_approver
            ON approval_node_instances (tenant_id, approver_id)
            WHERE status = 'pending';

        CREATE INDEX IF NOT EXISTS ix_ani_tenant_id
            ON approval_node_instances (tenant_id);
    """)

    # RLS
    op.execute("ALTER TABLE approval_node_instances ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE approval_node_instances FORCE ROW LEVEL SECURITY;")
    for op_name in ("select", "insert", "update", "delete"):
        check = f"WITH CHECK ({_RLS_COND})" if op_name in ("insert", "update") else ""
        op.execute(f"""
            CREATE POLICY rls_ani_{op_name}
                ON approval_node_instances
                FOR {op_name.upper()}
                USING ({_RLS_COND})
                {check};
        """)

    # ─────────────────────────────────────────────────────────────────
    # 5. 预置系统级审批流模板（system_seed 函数，由应用层调用）
    #    此处仅建 seed 函数，不在迁移中硬编码租户数据
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION seed_default_approval_templates(p_tenant_id UUID)
        RETURNS VOID LANGUAGE plpgsql AS $$
        DECLARE
            v_leave_tmpl_id    UUID;
            v_purchase_tmpl_id UUID;
            v_discount_tmpl_id UUID;
            v_price_tmpl_id    UUID;
        BEGIN
            -- 1. 请假审批：直属上级(level≥3) → 店长(level≥7)
            INSERT INTO approval_flow_templates
                (tenant_id, template_name, business_type, trigger_conditions)
            VALUES
                (p_tenant_id, '请假审批', 'leave', '{}')
            RETURNING id INTO v_leave_tmpl_id;

            INSERT INTO approval_flow_nodes
                (tenant_id, template_id, node_order, node_name,
                 node_type, approver_role_level, approve_type, timeout_hours, timeout_action)
            VALUES
                (p_tenant_id, v_leave_tmpl_id, 1, '直属上级',
                 'role_level', 3, 'any_one', 24, 'escalate'),
                (p_tenant_id, v_leave_tmpl_id, 2, '店长',
                 'role_level', 7, 'any_one', 48, 'auto_approve');

            -- 2. 采购审批：金额<1000自动通过；≥1000需店长(level≥7)；≥10000需区域总监(level≥9)
            INSERT INTO approval_flow_templates
                (tenant_id, template_name, business_type, trigger_conditions)
            VALUES
                (p_tenant_id, '采购审批', 'purchase',
                 '{"amount": {"op": ">=", "value": 100000}}')
            RETURNING id INTO v_purchase_tmpl_id;

            INSERT INTO approval_flow_nodes
                (tenant_id, template_id, node_order, node_name,
                 node_type, approver_role_level, approve_type,
                 auto_approve_condition, timeout_hours, timeout_action)
            VALUES
                (p_tenant_id, v_purchase_tmpl_id, 1, '店长审批',
                 'role_level', 7, 'any_one',
                 '{"amount": {"op": "<", "value": 1000000}}',
                 24, 'auto_approve'),
                (p_tenant_id, v_purchase_tmpl_id, 2, '区域总监审批',
                 'role_level', 9, 'any_one',
                 NULL,
                 48, 'auto_reject');

            -- 3. 大额折扣审批：任何超过角色权限的折扣→店长审批
            INSERT INTO approval_flow_templates
                (tenant_id, template_name, business_type, trigger_conditions)
            VALUES
                (p_tenant_id, '大额折扣审批', 'discount', '{}')
            RETURNING id INTO v_discount_tmpl_id;

            INSERT INTO approval_flow_nodes
                (tenant_id, template_id, node_order, node_name,
                 node_type, approver_role_level, approve_type, timeout_hours, timeout_action)
            VALUES
                (p_tenant_id, v_discount_tmpl_id, 1, '店长审批',
                 'role_level', 7, 'any_one', 24, 'auto_reject');

            -- 4. 价格调整审批：任何价格改动→品牌运营审批(level≥8)
            INSERT INTO approval_flow_templates
                (tenant_id, template_name, business_type, trigger_conditions)
            VALUES
                (p_tenant_id, '价格调整审批', 'price_change', '{}')
            RETURNING id INTO v_price_tmpl_id;

            INSERT INTO approval_flow_nodes
                (tenant_id, template_id, node_order, node_name,
                 node_type, approver_role_level, approve_type, timeout_hours, timeout_action)
            VALUES
                (p_tenant_id, v_price_tmpl_id, 1, '品牌运营审批',
                 'role_level', 8, 'any_one', 48, 'auto_reject');
        END;
        $$;

        COMMENT ON FUNCTION seed_default_approval_templates(UUID) IS
            '为指定租户预置 4 种默认审批流模板（请假/采购/折扣/价格调整）';
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS seed_default_approval_templates(UUID);")

    # 移除 approval_node_instances RLS 策略
    for op_name in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS rls_ani_{op_name} ON approval_node_instances;")
    op.execute("DROP TABLE IF EXISTS approval_node_instances CASCADE;")

    # 移除 approval_flow_nodes RLS 策略
    for op_name in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS rls_afn_{op_name} ON approval_flow_nodes;")
    op.execute("DROP TABLE IF EXISTS approval_flow_nodes CASCADE;")

    # 移除 approval_flow_templates RLS 策略
    for op_name in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS rls_aft_{op_name} ON approval_flow_templates;")
    op.execute("DROP TABLE IF EXISTS approval_flow_templates CASCADE;")

    # 回滚 approval_instances 新增字段（幂等）
    for col in ("flow_template_id", "store_id", "current_node_order", "summary", "completed_at"):
        op.execute(
            f"ALTER TABLE approval_instances DROP COLUMN IF EXISTS {col};"
        )
    op.execute("DROP INDEX IF EXISTS ix_ai_flow_template;")
    op.execute("DROP INDEX IF EXISTS ix_ai_store_status;")
