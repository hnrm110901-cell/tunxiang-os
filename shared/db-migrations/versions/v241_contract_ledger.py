"""合同台账系统：合同主表 + 付款计划 + 合同预警记录
Tables: contracts, contract_payments, contract_alerts
Sprint: P1-S5（合同台账 + A4预算预警Agent）

设计原则：
  - 合同管理涵盖门店租约、设备采购、服务外包等各类合同
  - 付款计划支持多期付款，逐期跟踪到期和实付
  - 合同预警幂等创建，避免重复推送

Revision ID: v241
Revises: v240
Create Date: 2026-04-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "v241"
down_revision = "v240b"
branch_labels = None
depends_on = None

# 标准安全 RLS 条件（NULLIF 保护，与 v239 规范一致）
_RLS_COND = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 表1：contracts（合同主表）
    # ------------------------------------------------------------------
    op.create_table(
        "contracts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),

        sa.Column("contract_no", sa.String(64), nullable=True,
                  comment="合同编号（租户内唯一）"),
        sa.Column("contract_name", sa.String(200), nullable=False,
                  comment="合同名称"),
        sa.Column("contract_type", sa.String(32), nullable=True,
                  comment="合同类型：rental/equipment/service/labor/other"),

        sa.Column("counterparty_name", sa.String(200), nullable=True,
                  comment="乙方/甲方名称"),
        sa.Column("counterparty_contact", sa.String(100), nullable=True,
                  comment="对方联系人"),

        sa.Column("total_amount", sa.BigInteger(), nullable=True,
                  comment="合同总金额（分），展示时除以100转元"),
        sa.Column("paid_amount", sa.BigInteger(), nullable=True,
                  server_default="0",
                  comment="已付金额（分），展示时除以100转元"),

        sa.Column("start_date", sa.Date(), nullable=True,
                  comment="合同开始日期"),
        sa.Column("end_date", sa.Date(), nullable=True,
                  comment="合同结束日期"),

        sa.Column("auto_renew", sa.Boolean(), nullable=True,
                  server_default="false",
                  comment="是否自动续约"),
        sa.Column("renewal_notice_days", sa.Integer(), nullable=True,
                  server_default="30",
                  comment="提前N天提醒续签"),

        sa.Column("status", sa.String(32), nullable=False,
                  server_default="active",
                  comment="合同状态：draft/active/expired/terminated"),

        sa.Column("store_id", UUID(as_uuid=True), nullable=True,
                  comment="关联门店ID"),
        sa.Column("responsible_person", UUID(as_uuid=True), nullable=True,
                  comment="合同负责人员工ID"),

        sa.Column("file_url", sa.Text(), nullable=True,
                  comment="合同附件URL（Supabase Storage）"),
        sa.Column("notes", sa.Text(), nullable=True,
                  comment="备注"),

        sa.Column("created_by", UUID(as_uuid=True), nullable=True,
                  comment="创建人"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=True,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True,
                  server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean(), nullable=True,
                  server_default="false"),
    )

    # 唯一约束：contract_no 在租户内唯一（忽略已删除）
    op.create_unique_constraint(
        "uq_contracts_tenant_contract_no",
        "contracts",
        ["tenant_id", "contract_no"],
    )

    # 索引
    op.create_index(
        "ix_contracts_tenant_status",
        "contracts",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_contracts_tenant_end_date",
        "contracts",
        ["tenant_id", "end_date"],
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_contracts_tenant_store_id",
        "contracts",
        ["tenant_id", "store_id"],
    )
    op.create_index(
        "ix_contracts_tenant_type",
        "contracts",
        ["tenant_id", "contract_type"],
    )

    # RLS
    op.execute("ALTER TABLE contracts ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY contracts_tenant_isolation
        ON contracts
        USING ({_RLS_COND})
        """
    )

    # ------------------------------------------------------------------
    # 表2：contract_payments（付款计划）
    # ------------------------------------------------------------------
    op.create_table(
        "contract_payments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("contract_id", UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["contract_id"],
            ["contracts.id"],
            name="fk_contract_payments_contract_id",
            ondelete="CASCADE",
        ),

        sa.Column("period_name", sa.String(100), nullable=True,
                  comment="期次名称，如'2026年Q1'"),
        sa.Column("due_date", sa.Date(), nullable=False,
                  comment="计划付款日期"),

        sa.Column("planned_amount", sa.BigInteger(), nullable=False,
                  comment="计划付款金额（分），展示时除以100转元"),
        sa.Column("actual_amount", sa.BigInteger(), nullable=True,
                  comment="实际付款金额（分），展示时除以100转元"),

        sa.Column("status", sa.String(32), nullable=False,
                  server_default="pending",
                  comment="付款状态：pending/paid/overdue/cancelled"),

        sa.Column("paid_at", sa.TIMESTAMP(timezone=True), nullable=True,
                  comment="实际付款时间"),
        sa.Column("notes", sa.Text(), nullable=True,
                  comment="备注"),

        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=True,
                  server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean(), nullable=True,
                  server_default="false"),
    )

    # 索引
    op.create_index(
        "ix_contract_payments_tenant_contract",
        "contract_payments",
        ["tenant_id", "contract_id"],
    )
    op.create_index(
        "ix_contract_payments_tenant_due_date_status",
        "contract_payments",
        ["tenant_id", "due_date", "status"],
    )
    op.create_index(
        "ix_contract_payments_tenant_status",
        "contract_payments",
        ["tenant_id", "status"],
        postgresql_where=sa.text("is_deleted = false"),
    )

    # RLS
    op.execute("ALTER TABLE contract_payments ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY contract_payments_tenant_isolation
        ON contract_payments
        USING ({_RLS_COND})
        """
    )

    # ------------------------------------------------------------------
    # 表3：contract_alerts（合同预警记录）
    # ------------------------------------------------------------------
    op.create_table(
        "contract_alerts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("contract_id", UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["contract_id"],
            ["contracts.id"],
            name="fk_contract_alerts_contract_id",
            ondelete="CASCADE",
        ),

        sa.Column("alert_type", sa.String(32), nullable=True,
                  comment="预警类型：expiry/payment_due/auto_renew/overspend"),
        sa.Column("alert_days_before", sa.Integer(), nullable=True,
                  comment="提前多少天触发预警"),
        sa.Column("message", sa.Text(), nullable=True,
                  comment="预警消息内容"),

        sa.Column("is_sent", sa.Boolean(), nullable=True,
                  server_default="false",
                  comment="是否已推送"),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True), nullable=True,
                  comment="推送时间"),

        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=True,
                  server_default=sa.text("now()")),
    )

    # 索引
    op.create_index(
        "ix_contract_alerts_tenant_contract",
        "contract_alerts",
        ["tenant_id", "contract_id"],
    )
    op.create_index(
        "ix_contract_alerts_tenant_is_sent",
        "contract_alerts",
        ["tenant_id", "is_sent"],
    )
    op.create_index(
        "ix_contract_alerts_tenant_type_date",
        "contract_alerts",
        ["tenant_id", "alert_type", sa.text("created_at::date")],
    )

    # RLS
    op.execute("ALTER TABLE contract_alerts ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY contract_alerts_tenant_isolation
        ON contract_alerts
        USING ({_RLS_COND})
        """
    )


def downgrade() -> None:
    # 按依赖反向删除

    # contract_alerts
    op.execute("DROP POLICY IF EXISTS contract_alerts_tenant_isolation ON contract_alerts")
    op.drop_table("contract_alerts")

    # contract_payments
    op.execute("DROP POLICY IF EXISTS contract_payments_tenant_isolation ON contract_payments")
    op.drop_table("contract_payments")

    # contracts
    op.execute("DROP POLICY IF EXISTS contracts_tenant_isolation ON contracts")
    op.drop_table("contracts")
