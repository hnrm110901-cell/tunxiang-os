"""v031: 添加营销审批流表（approval_workflows + approval_requests）

新增两张表：
  approval_workflows  — 审批流模板（触发条件 + 审批步骤，JSONB存储）
  approval_requests   — 审批单（每次触发审批产生一条记录，含审批历史 JSONB）

内置审批流模板（通过代码 seed，不在迁移中硬编码租户数据）：
  - 大额优惠审批：max_discount_fen > 5000（优惠 >50元），店长24小时审批
  - 大规模活动审批：target_count > 500（目标人数 >500），区域经理48小时审批（超时自动通过）

索引：
  approval_workflows:
    - (tenant_id, is_active)      — 触发条件检查
    - (tenant_id, priority)       — 优先级排序
  approval_requests:
    - (tenant_id, status)         — 待审批列表
    - (tenant_id, object_type, object_id) — 幂等检查
    - (tenant_id, requester_id)   — 申请人视角
    - (tenant_id, expires_at) WHERE status='pending' — 超时定时任务

RLS 策略：
  使用 v006+ 标准安全模式（app.tenant_id + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v031
Revises: v030
Create Date: 2026-03-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "v033"
down_revision = "v032"
branch_labels = None
depends_on = None

# RLS 条件（v006+ 标准模式）
_RLS_COND = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = current_setting('app.tenant_id')::UUID"
)


def upgrade() -> None:
    # ----------------------------------------------------------------
    # 1. approval_workflows — 审批流模板
    # ----------------------------------------------------------------
    op.create_table(
        "approval_workflows",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "is_deleted", sa.Boolean(), nullable=False, server_default="false"
        ),

        sa.Column(
            "name", sa.String(100), nullable=False,
            comment="审批流名称，如：大额优惠审批流",
        ),
        sa.Column(
            "trigger_conditions", JSONB, nullable=False, server_default=sa.text("'{}'"),
            comment="触发条件 JSONB: {type, conditions:[{field, op, value}]}",
        ),
        sa.Column(
            "steps", JSONB, nullable=False, server_default=sa.text("'[]'"),
            comment="审批步骤列表 JSONB: [{step, role, timeout_hours, auto_approve_on_timeout}]",
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default="true",
            comment="是否启用",
        ),
        sa.Column(
            "priority", sa.Integer(), nullable=False, server_default="0",
            comment="优先级（值越大越优先），多个工作流匹配时取最高",
        ),

        comment="审批流模板表",
    )

    op.create_index(
        "idx_approval_workflows_tenant_id",
        "approval_workflows",
        ["tenant_id"],
    )
    op.create_index(
        "idx_approval_workflows_tenant_active",
        "approval_workflows",
        ["tenant_id", "is_active"],
    )
    op.create_index(
        "idx_approval_workflows_tenant_priority",
        "approval_workflows",
        ["tenant_id", "priority"],
    )

    # ----------------------------------------------------------------
    # 2. approval_requests — 审批单
    # ----------------------------------------------------------------
    op.create_table(
        "approval_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "is_deleted", sa.Boolean(), nullable=False, server_default="false"
        ),

        # 关联审批流模板（软关联，不设 FK 避免跨租户约束问题）
        sa.Column("workflow_id", UUID(as_uuid=True), nullable=False,
                  comment="所属审批流模板 ID"),

        # 审批对象
        sa.Column(
            "object_type", sa.String(50), nullable=False,
            comment="campaign | journey | referral_campaign | stored_value_plan",
        ),
        sa.Column(
            "object_id", sa.String(64), nullable=False,
            comment="被审批对象 ID",
        ),
        sa.Column(
            "object_summary", JSONB, nullable=False, server_default=sa.text("'{}'"),
            comment="审批内容摘要 JSONB，冗余存储减少关联查询",
        ),

        # 申请人
        sa.Column(
            "requester_id", UUID(as_uuid=True), nullable=False,
            comment="申请人员工 ID",
        ),
        sa.Column(
            "requester_name", sa.String(50), nullable=False,
            comment="申请人姓名（冗余存储）",
        ),

        # 状态
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="pending",
            comment="pending | approved | rejected | cancelled | expired",
        ),
        sa.Column(
            "current_step", sa.Integer(), nullable=False, server_default="1",
            comment="当前审批步骤编号（从1开始）",
        ),

        # 审批历史（追加写，永不更新）
        sa.Column(
            "approval_history", JSONB, nullable=False, server_default=sa.text("'[]'"),
            comment="审批操作历史列表 JSONB",
        ),

        sa.Column(
            "reject_reason", sa.Text(), nullable=True,
            comment="拒绝原因",
        ),

        # 时间戳
        sa.Column(
            "approved_at", sa.DateTime(timezone=True), nullable=True,
            comment="全部审批通过时间",
        ),
        sa.Column(
            "expires_at", sa.DateTime(timezone=True), nullable=True,
            comment="当前步骤超时时间（now + step.timeout_hours）",
        ),

        comment="审批单表",
    )

    op.create_index(
        "idx_approval_requests_tenant_id",
        "approval_requests",
        ["tenant_id"],
    )
    op.create_index(
        "idx_approval_requests_tenant_status",
        "approval_requests",
        ["tenant_id", "status"],
    )
    op.create_index(
        "idx_approval_requests_tenant_object",
        "approval_requests",
        ["tenant_id", "object_type", "object_id"],
    )
    op.create_index(
        "idx_approval_requests_requester",
        "approval_requests",
        ["tenant_id", "requester_id"],
    )
    # 部分索引：仅对 pending 状态建超时查询索引，减少索引体积
    op.create_index(
        "idx_approval_requests_expires_pending",
        "approval_requests",
        ["tenant_id", "expires_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "idx_approval_requests_workflow_id",
        "approval_requests",
        ["workflow_id"],
    )

    # ----------------------------------------------------------------
    # 3. RLS — approval_workflows
    # ----------------------------------------------------------------
    op.execute("ALTER TABLE approval_workflows ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE approval_workflows FORCE ROW LEVEL SECURITY;")

    op.execute(f"""
        CREATE POLICY rls_approval_workflows_select
            ON approval_workflows FOR SELECT
            USING ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_approval_workflows_insert
            ON approval_workflows FOR INSERT
            WITH CHECK ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_approval_workflows_update
            ON approval_workflows FOR UPDATE
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_approval_workflows_delete
            ON approval_workflows FOR DELETE
            USING ({_RLS_COND});
    """)

    # ----------------------------------------------------------------
    # 4. RLS — approval_requests
    # ----------------------------------------------------------------
    op.execute("ALTER TABLE approval_requests ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE approval_requests FORCE ROW LEVEL SECURITY;")

    op.execute(f"""
        CREATE POLICY rls_approval_requests_select
            ON approval_requests FOR SELECT
            USING ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_approval_requests_insert
            ON approval_requests FOR INSERT
            WITH CHECK ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_approval_requests_update
            ON approval_requests FOR UPDATE
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_approval_requests_delete
            ON approval_requests FOR DELETE
            USING ({_RLS_COND});
    """)


def downgrade() -> None:
    # ---- approval_requests ----
    for policy in [
        "rls_approval_requests_select",
        "rls_approval_requests_insert",
        "rls_approval_requests_update",
        "rls_approval_requests_delete",
    ]:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON approval_requests;")
    op.execute("ALTER TABLE approval_requests DISABLE ROW LEVEL SECURITY;")

    # ---- approval_workflows ----
    for policy in [
        "rls_approval_workflows_select",
        "rls_approval_workflows_insert",
        "rls_approval_workflows_update",
        "rls_approval_workflows_delete",
    ]:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON approval_workflows;")
    op.execute("ALTER TABLE approval_workflows DISABLE ROW LEVEL SECURITY;")

    # 删索引
    for idx, tbl in [
        ("idx_approval_requests_workflow_id", "approval_requests"),
        ("idx_approval_requests_expires_pending", "approval_requests"),
        ("idx_approval_requests_requester", "approval_requests"),
        ("idx_approval_requests_tenant_object", "approval_requests"),
        ("idx_approval_requests_tenant_status", "approval_requests"),
        ("idx_approval_requests_tenant_id", "approval_requests"),
        ("idx_approval_workflows_tenant_priority", "approval_workflows"),
        ("idx_approval_workflows_tenant_active", "approval_workflows"),
        ("idx_approval_workflows_tenant_id", "approval_workflows"),
    ]:
        op.drop_index(idx, table_name=tbl)

    op.drop_table("approval_requests")
    op.drop_table("approval_workflows")
