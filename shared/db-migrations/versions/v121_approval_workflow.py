"""v121 — 审批流引擎核心表

新增四张表：
  approval_templates      — 审批流模板（按业务类型+金额区间匹配步骤）
  approval_instances      — 审批实例（每次发起审批的主记录）
  approval_step_records   — 步骤操作记录（每次审批/驳回/转交的快照）
  approval_notifications  — 审批通知（待审/结果通知/提醒）

Revision ID: v121
Revises: v120
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "v121"
down_revision = "v120"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── approval_templates 审批流模板 ────────────────────────────────────
    op.create_table(
        "approval_templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("template_name", sa.String(100), nullable=False),
        sa.Column(
            "business_type", sa.String(30), nullable=False,
            comment="discount/refund/void_order/large_purchase/staff_leave/payroll",
        ),
        sa.Column(
            "steps", JSONB, nullable=False,
            server_default="'[]'",
            comment=(
                "审批步骤数组，每步含: "
                "step_no(int), role(str), approver_type(role|specific_user), "
                "min_amount_fen(int|null), max_amount_fen(int|null)"
            ),
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index(
        "ix_approval_templates_tenant_type",
        "approval_templates",
        ["tenant_id", "business_type"],
    )
    op.create_index(
        "ix_approval_templates_tenant_active",
        "approval_templates",
        ["tenant_id", "is_active"],
    )

    op.execute("ALTER TABLE approval_templates ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY approval_templates_tenant_isolation ON approval_templates
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── approval_instances 审批实例 ──────────────────────────────────────
    op.create_table(
        "approval_instances",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "template_id", UUID(as_uuid=True), nullable=True,
            comment="FK → approval_templates.id（模板删除后保留历史）",
        ),
        sa.Column(
            "business_type", sa.String(30), nullable=False,
            comment="discount/refund/void_order/large_purchase/staff_leave/payroll",
        ),
        sa.Column(
            "business_id", sa.String(100), nullable=False,
            comment="关联业务单号（订单ID/薪资单ID等）",
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("amount_fen", sa.Integer, nullable=True, comment="涉及金额（分），可空"),
        sa.Column("initiator_id", sa.String(100), nullable=False),
        sa.Column("initiator_name", sa.String(100), nullable=False),
        sa.Column("current_step", sa.Integer, nullable=False, server_default="1"),
        sa.Column("total_steps", sa.Integer, nullable=False, server_default="1"),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="'pending'",
            comment="pending/approved/rejected/cancelled/expired",
        ),
        sa.Column(
            "deadline_at", sa.TIMESTAMP(timezone=True), nullable=True,
            comment="超时自动拒绝时间",
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index(
        "ix_approval_instances_tenant_status",
        "approval_instances",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_approval_instances_tenant_initiator",
        "approval_instances",
        ["tenant_id", "initiator_id"],
    )
    op.create_index(
        "ix_approval_instances_tenant_type",
        "approval_instances",
        ["tenant_id", "business_type"],
    )
    op.create_index(
        "ix_approval_instances_deadline",
        "approval_instances",
        ["deadline_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    # FK（软引用，允许模板删除后实例仍存活）
    op.create_foreign_key(
        "fk_approval_instances_template",
        "approval_instances", "approval_templates",
        ["template_id"], ["id"],
        ondelete="SET NULL",
    )

    op.execute("ALTER TABLE approval_instances ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY approval_instances_tenant_isolation ON approval_instances
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── approval_step_records 审批步骤记录 ───────────────────────────────
    op.create_table(
        "approval_step_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "instance_id", UUID(as_uuid=True), nullable=False,
            comment="FK → approval_instances.id",
        ),
        sa.Column("step_no", sa.Integer, nullable=False),
        sa.Column("approver_id", sa.String(100), nullable=False),
        sa.Column("approver_name", sa.String(100), nullable=False),
        sa.Column("approver_role", sa.String(50), nullable=False),
        sa.Column(
            "action", sa.String(20), nullable=False,
            comment="approve/reject/delegate",
        ),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column(
            "delegated_to", sa.String(100), nullable=True,
            comment="转交目标人员ID（action=delegate时有值）",
        ),
        sa.Column("acted_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_approval_step_records_instance",
        "approval_step_records",
        ["instance_id"],
    )
    op.create_index(
        "ix_approval_step_records_tenant_approver",
        "approval_step_records",
        ["tenant_id", "approver_id"],
    )
    op.create_foreign_key(
        "fk_approval_step_records_instance",
        "approval_step_records", "approval_instances",
        ["instance_id"], ["id"],
        ondelete="CASCADE",
    )

    op.execute("ALTER TABLE approval_step_records ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY approval_step_records_tenant_isolation ON approval_step_records
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── approval_notifications 审批通知 ──────────────────────────────────
    op.create_table(
        "approval_notifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "instance_id", UUID(as_uuid=True), nullable=False,
            comment="FK → approval_instances.id",
        ),
        sa.Column("recipient_id", sa.String(100), nullable=False),
        sa.Column("recipient_name", sa.String(100), nullable=False),
        sa.Column(
            "notification_type", sa.String(20), nullable=False,
            comment="pending/approved/rejected/reminder",
        ),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("is_read", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("read_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_approval_notifications_tenant_recipient",
        "approval_notifications",
        ["tenant_id", "recipient_id"],
    )
    op.create_index(
        "ix_approval_notifications_recipient_unread",
        "approval_notifications",
        ["tenant_id", "recipient_id", "is_read"],
    )
    op.create_index(
        "ix_approval_notifications_instance",
        "approval_notifications",
        ["instance_id"],
    )
    op.create_foreign_key(
        "fk_approval_notifications_instance",
        "approval_notifications", "approval_instances",
        ["instance_id"], ["id"],
        ondelete="CASCADE",
    )

    op.execute("ALTER TABLE approval_notifications ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY approval_notifications_tenant_isolation ON approval_notifications
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS approval_notifications_tenant_isolation ON approval_notifications;")
    op.drop_table("approval_notifications")

    op.execute("DROP POLICY IF EXISTS approval_step_records_tenant_isolation ON approval_step_records;")
    op.drop_table("approval_step_records")

    op.execute("DROP POLICY IF EXISTS approval_instances_tenant_isolation ON approval_instances;")
    op.drop_table("approval_instances")

    op.execute("DROP POLICY IF EXISTS approval_templates_tenant_isolation ON approval_templates;")
    op.drop_table("approval_templates")
