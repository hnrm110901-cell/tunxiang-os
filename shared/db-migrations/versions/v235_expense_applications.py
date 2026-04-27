"""v235 — 费用申请核心：申请主表 + 明细行 + 附件 + 审批引擎表

费控系统 P0-S1/P0-S2 核心层：
  - expense_applications    费用申请主表（状态机驱动：draft→submitted→in_review→approved/rejected→paid）
  - expense_items           申请明细行（每行一个费用科目，金额单位：分）
  - expense_attachments     申请附件（发票/小票图片，Supabase Storage URL）
  - approval_routing_rules  审批路由规则（按金额区间/场景分配审批角色）
  - approval_instances      审批实例（每个申请唯一，存储完整审批链快照）
  - approval_nodes          审批节点（按顺序记录每位审批人的操作结果）

Tables: expense_applications, expense_items, expense_attachments,
        approval_routing_rules, approval_instances, approval_nodes
Sprint: P0-S1, P0-S2

RLS 采用 NULLIF 安全格式，防止 app.tenant_id 为空时发生跨租户数据泄露。
所有金额字段单位为分（fen），前端展示时除以 100 转换为元。

Revision ID: v235
Revises: v234
Create Date: 2026-04-12
"""

import sqlalchemy as sa
from alembic import op

revision = "v235"
down_revision = "v234c"
branch_labels = None
depends_on = None

# 标准安全 RLS 条件（NULLIF 保护，与 v231 规范一致）
_RLS_COND = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()
    if "expense_applications" in existing:
        return

    # ──────────────────────────────────────────────────────────────────
    # expense_applications — 费用申请主表
    # ──────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS expense_applications (
            id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID        NOT NULL,
            brand_id         UUID        NOT NULL,
            store_id         UUID        NOT NULL,
            applicant_id     UUID        NOT NULL,
            scenario_id      UUID        NOT NULL REFERENCES expense_scenarios(id),
            title            VARCHAR(200) NOT NULL,
            total_amount     BIGINT      NOT NULL,
            currency         VARCHAR(3)   NOT NULL DEFAULT 'CNY',
            status           VARCHAR(30)  NOT NULL DEFAULT 'draft',
            legal_entity_id  UUID,
            purpose          TEXT,
            notes            TEXT,
            metadata         JSONB        NOT NULL DEFAULT '{}'::jsonb,
            submitted_at     TIMESTAMPTZ,
            approved_at      TIMESTAMPTZ,
            rejected_at      TIMESTAMPTZ,
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted       BOOLEAN      NOT NULL DEFAULT FALSE
        );

        COMMENT ON TABLE expense_applications IS
            '费用申请主表：状态机驱动，覆盖差旅/餐饮/采购等全场景费用申请生命周期';
        COMMENT ON COLUMN expense_applications.applicant_id IS
            '申请人员工 ID，对应 employees.id';
        COMMENT ON COLUMN expense_applications.total_amount IS
            '单位：分(fen)，展示时除以100转元；等于所有 expense_items.amount × quantity 之和';
        COMMENT ON COLUMN expense_applications.currency IS
            '币种代码（ISO 4217），默认 CNY，多币种场景扩展用';
        COMMENT ON COLUMN expense_applications.status IS
            '申请状态：draft=草稿 / submitted=已提交 / in_review=审批中 / approved=已批准 / rejected=已拒绝 / paid=已付款 / cancelled=已撤销';
        COMMENT ON COLUMN expense_applications.legal_entity_id IS
            '法人主体 ID，多法人场景下用于凭证分拆，单法人品牌可为 NULL';
        COMMENT ON COLUMN expense_applications.metadata IS
            '场景自定义字段（JSONB），存储场景特有的补充信息，如差旅目的地/出差天数等';

        CREATE INDEX IF NOT EXISTS ix_expense_applications_tenant_store_status
            ON expense_applications (tenant_id, store_id, status);

        CREATE INDEX IF NOT EXISTS ix_expense_applications_tenant_applicant
            ON expense_applications (tenant_id, applicant_id);

        CREATE INDEX IF NOT EXISTS ix_expense_applications_tenant_created
            ON expense_applications (tenant_id, created_at DESC);

        CREATE INDEX IF NOT EXISTS ix_expense_applications_tenant_not_deleted
            ON expense_applications (tenant_id, is_deleted)
            WHERE is_deleted = FALSE;
    """)

    op.execute("ALTER TABLE expense_applications ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE expense_applications FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY expense_applications_rls ON expense_applications
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)

    # ──────────────────────────────────────────────────────────────────
    # expense_items — 申请明细行
    # ──────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS expense_items (
            id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID        NOT NULL,
            application_id   UUID        NOT NULL REFERENCES expense_applications(id) ON DELETE CASCADE,
            category_id      UUID        NOT NULL REFERENCES expense_categories(id),
            description      VARCHAR(200) NOT NULL,
            amount           BIGINT      NOT NULL,
            quantity         NUMERIC(10,2) NOT NULL DEFAULT 1,
            unit             VARCHAR(20),
            invoice_id       UUID,
            expense_date     DATE        NOT NULL,
            notes            TEXT,
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );

        COMMENT ON TABLE expense_items IS
            '费用申请明细行：每行对应一个费用科目，支持数量×单价拆分；与申请主表级联删除';
        COMMENT ON COLUMN expense_items.amount IS
            '单位：分(fen)，展示时除以100转元；单行金额 = amount × quantity（前端计算）';
        COMMENT ON COLUMN expense_items.quantity IS
            '数量，默认 1；配合 unit 使用，如 2 张、3 天、1 次';
        COMMENT ON COLUMN expense_items.unit IS
            '数量单位，如 张/次/天/个/公里；NULL 表示无单位';
        COMMENT ON COLUMN expense_items.invoice_id IS
            '关联发票 ID（预留，P1阶段接入 invoices 表外键约束）';
        COMMENT ON COLUMN expense_items.expense_date IS
            '费用实际发生日期（非申请日期），用于财务期间归属';

        CREATE INDEX IF NOT EXISTS ix_expense_items_tenant_application
            ON expense_items (tenant_id, application_id);

        CREATE INDEX IF NOT EXISTS ix_expense_items_tenant_category
            ON expense_items (tenant_id, category_id);
    """)

    op.execute("ALTER TABLE expense_items ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE expense_items FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY expense_items_rls ON expense_items
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)

    # ──────────────────────────────────────────────────────────────────
    # expense_attachments — 申请附件
    # ──────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS expense_attachments (
            id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID        NOT NULL,
            application_id   UUID        NOT NULL REFERENCES expense_applications(id) ON DELETE CASCADE,
            file_name        VARCHAR(255) NOT NULL,
            file_url         TEXT        NOT NULL,
            file_type        VARCHAR(50),
            file_size        INTEGER,
            uploaded_by      UUID        NOT NULL,
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );

        COMMENT ON TABLE expense_attachments IS
            '费用申请附件：发票/小票/合同扫描件，存储于 Supabase Storage，与申请主表级联删除';
        COMMENT ON COLUMN expense_attachments.file_url IS
            'Supabase Storage 公开访问 URL，格式：{storage_base}/expense-attachments/{tenant_id}/{file_name}';
        COMMENT ON COLUMN expense_attachments.file_type IS
            'MIME 类型，如 image/jpeg / image/png / application/pdf';
        COMMENT ON COLUMN expense_attachments.file_size IS
            '文件大小（bytes），用于前端展示和存储配额管理；NULL 表示未记录';
        COMMENT ON COLUMN expense_attachments.uploaded_by IS
            '上传操作人员工 ID（通常为申请人，审批人补传发票时也可能是其他人）';

        CREATE INDEX IF NOT EXISTS ix_expense_attachments_tenant_application
            ON expense_attachments (tenant_id, application_id);
    """)

    op.execute("ALTER TABLE expense_attachments ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE expense_attachments FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY expense_attachments_rls ON expense_attachments
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)

    # ──────────────────────────────────────────────────────────────────
    # approval_routing_rules — 审批路由规则
    # ──────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS approval_routing_rules (
            id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID        NOT NULL,
            brand_id         UUID        NOT NULL,
            scenario_code    VARCHAR(30),
            routing_type     VARCHAR(30)  NOT NULL DEFAULT 'amount_based',
            amount_min       BIGINT      NOT NULL DEFAULT 0,
            amount_max       BIGINT      NOT NULL DEFAULT -1,
            approver_role    VARCHAR(50)  NOT NULL,
            approver_count   INTEGER      NOT NULL DEFAULT 1,
            is_active        BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );

        COMMENT ON TABLE approval_routing_rules IS
            '审批路由规则：按金额区间和场景类型分配审批角色，支持品牌级精细化配置';
        COMMENT ON COLUMN approval_routing_rules.scenario_code IS
            '场景代码，NULL 表示适用于所有场景的通用规则，非 NULL 表示场景专用规则（优先级更高）';
        COMMENT ON COLUMN approval_routing_rules.routing_type IS
            '路由类型：amount_based=按金额分级 / scenario_fixed=场景固定链 / escalated=超时升级';
        COMMENT ON COLUMN approval_routing_rules.amount_min IS
            '单位：分(fen)，展示时除以100转元；金额区间下限，0 表示无下限';
        COMMENT ON COLUMN approval_routing_rules.amount_max IS
            '单位：分(fen)，展示时除以100转元；金额区间上限，-1 表示无上限';
        COMMENT ON COLUMN approval_routing_rules.approver_role IS
            '审批人角色：store_manager=店长 / region_manager=区域经理 / brand_finance=品牌财务 / brand_cfo=品牌CFO';
        COMMENT ON COLUMN approval_routing_rules.approver_count IS
            '该节点需要审批通过的人数，1=单人审批，>1=会签（需全部通过）';

        CREATE INDEX IF NOT EXISTS ix_approval_routing_rules_tenant_brand_type
            ON approval_routing_rules (tenant_id, brand_id, routing_type);

        CREATE INDEX IF NOT EXISTS ix_approval_routing_rules_tenant_brand_amount
            ON approval_routing_rules (tenant_id, brand_id, amount_min, amount_max);
    """)

    op.execute("ALTER TABLE approval_routing_rules ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE approval_routing_rules FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY approval_routing_rules_rls ON approval_routing_rules
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)

    # ──────────────────────────────────────────────────────────────────
    # approval_instances — 审批实例
    # ──────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS approval_instances (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID        NOT NULL,
            application_id      UUID        NOT NULL UNIQUE REFERENCES expense_applications(id),
            current_node_index  INTEGER      NOT NULL DEFAULT 0,
            total_nodes         INTEGER      NOT NULL,
            status              VARCHAR(30)  NOT NULL DEFAULT 'pending',
            routing_snapshot    JSONB        NOT NULL,
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );

        COMMENT ON TABLE approval_instances IS
            '审批实例：每个费用申请唯一对应一个审批实例，UNIQUE 约束保障幂等性';
        COMMENT ON COLUMN approval_instances.current_node_index IS
            '当前待审批节点的 0-based 索引；等于 total_nodes 时表示审批链已完成';
        COMMENT ON COLUMN approval_instances.total_nodes IS
            '审批链总节点数，由路由规则匹配结果决定，创建后不可更改';
        COMMENT ON COLUMN approval_instances.status IS
            '实例状态：pending=等待审批 / approved=全部通过 / rejected=被拒绝 / cancelled=已撤销';
        COMMENT ON COLUMN approval_instances.routing_snapshot IS
            '创建时的完整审批链快照（JSONB），记录规则匹配结果，防止规则变更影响历史审批流';

        CREATE INDEX IF NOT EXISTS ix_approval_instances_tenant_application
            ON approval_instances (tenant_id, application_id);

        CREATE INDEX IF NOT EXISTS ix_approval_instances_tenant_status
            ON approval_instances (tenant_id, status);
    """)

    op.execute("ALTER TABLE approval_instances ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE approval_instances FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY approval_instances_rls ON approval_instances
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)

    # ──────────────────────────────────────────────────────────────────
    # approval_nodes — 审批节点
    # ──────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS approval_nodes (
            id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID        NOT NULL,
            instance_id      UUID        NOT NULL REFERENCES approval_instances(id),
            node_index       INTEGER      NOT NULL,
            approver_id      UUID        NOT NULL,
            approver_role    VARCHAR(50)  NOT NULL,
            status           VARCHAR(30)  NOT NULL DEFAULT 'pending',
            action           VARCHAR(30),
            comment          TEXT,
            acted_at         TIMESTAMPTZ,
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );

        COMMENT ON TABLE approval_nodes IS
            '审批节点：记录审批链中每个审批人的操作结果，UNIQUE(instance_id, node_index) 保障顺序唯一';
        COMMENT ON COLUMN approval_nodes.node_index IS
            '节点在审批链中的 0-based 顺序索引，与 approval_instances.current_node_index 对应';
        COMMENT ON COLUMN approval_nodes.approver_id IS
            '审批人员工 ID，由审批引擎按角色从 employees 表动态解析后写入';
        COMMENT ON COLUMN approval_nodes.status IS
            '节点状态：pending=待审批 / approved=已批准 / rejected=已拒绝 / skipped=已跳过';
        COMMENT ON COLUMN approval_nodes.action IS
            '实际执行的审批动作：approve=批准 / reject=拒绝 / transfer=转审 / urge=催办';
        COMMENT ON COLUMN approval_nodes.comment IS
            '审批意见，拒绝时必填（由服务层业务校验），通过时可选';
        COMMENT ON COLUMN approval_nodes.acted_at IS
            '审批操作完成时间，NULL 表示尚未操作';

        CREATE INDEX IF NOT EXISTS ix_approval_nodes_tenant_instance
            ON approval_nodes (tenant_id, instance_id);

        CREATE INDEX IF NOT EXISTS ix_approval_nodes_tenant_approver_status
            ON approval_nodes (tenant_id, approver_id, status);

        CREATE UNIQUE INDEX IF NOT EXISTS uq_approval_nodes_instance_node_index
            ON approval_nodes (instance_id, node_index);
    """)

    op.execute("ALTER TABLE approval_nodes ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE approval_nodes FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY approval_nodes_rls ON approval_nodes
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)


def downgrade() -> None:
    # 按依赖顺序反向删除（先删叶子表，后删被引用表）

    # approval_nodes
    op.execute("DROP POLICY IF EXISTS approval_nodes_rls ON approval_nodes;")
    op.execute("DROP TABLE IF EXISTS approval_nodes CASCADE;")

    # approval_instances
    op.execute("DROP POLICY IF EXISTS approval_instances_rls ON approval_instances;")
    op.execute("DROP TABLE IF EXISTS approval_instances CASCADE;")

    # approval_routing_rules
    op.execute("DROP POLICY IF EXISTS approval_routing_rules_rls ON approval_routing_rules;")
    op.execute("DROP TABLE IF EXISTS approval_routing_rules CASCADE;")

    # expense_attachments
    op.execute("DROP POLICY IF EXISTS expense_attachments_rls ON expense_attachments;")
    op.execute("DROP TABLE IF EXISTS expense_attachments CASCADE;")

    # expense_items
    op.execute("DROP POLICY IF EXISTS expense_items_rls ON expense_items;")
    op.execute("DROP TABLE IF EXISTS expense_items CASCADE;")

    # expense_applications
    op.execute("DROP POLICY IF EXISTS expense_applications_rls ON expense_applications;")
    op.execute("DROP TABLE IF EXISTS expense_applications CASCADE;")
