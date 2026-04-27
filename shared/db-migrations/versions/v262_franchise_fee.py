"""v262 — tx-org 新增：加盟收费闭环

新建：
  franchise_fee_bills         — 加盟费账单主表
  franchise_fee_payments      — 收款记录（支持部分付款）
  franchise_billing_rules     — 自动出账规则配置
  franchise_reminder_logs     — 催款提醒发送日志

账单状态流转：pending → partial → paid / overdue / cancelled
支持四类费用：joining_fee / royalty / ad_fee / supply_fee

所有含 tenant_id 的表启用 RLS（app.tenant_id）。

Revision ID: v262
Revises: v261
Create Date: 2026-04-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "v262"
down_revision = "v261"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # ── franchise_fee_bills ───────────────────────────────────────────────────
    if "franchise_fee_bills" not in existing:
        op.create_table(
            "franchise_fee_bills",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "franchise_id", UUID(as_uuid=True), nullable=False, comment="加盟商 ID（逻辑引用 franchises.id）"
            ),
            sa.Column(
                "bill_no",
                sa.String(50),
                nullable=True,
                unique=True,
                comment="账单编号（系统自动生成，格式：FB{YYYYMM}{6位序号}）",
            ),
            sa.Column(
                "bill_type",
                sa.String(30),
                nullable=True,
                comment="joining_fee=加盟费 / royalty=特许经营费 / ad_fee=广告费 / supply_fee=供应链服务费",
            ),
            sa.Column("amount_fen", sa.BigInteger, nullable=False, comment="应收金额（分）"),
            sa.Column(
                "paid_amount_fen", sa.BigInteger, nullable=False, server_default="0", comment="已收金额（分），累计值"
            ),
            sa.Column("due_date", sa.Date, nullable=False, comment="账单到期日"),
            sa.Column("billing_period", sa.String(20), nullable=True, comment="账期，格式：2026-03（月度账单用）"),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="'pending'",
                comment="pending=待付 / partial=部分付款 / paid=已付清 / overdue=已逾期 / cancelled=已取消",
            ),
            sa.Column("notes", sa.Text, nullable=True, comment="账单备注"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
        op.create_index("ix_franchise_fee_bills_tenant_franchise", "franchise_fee_bills", ["tenant_id", "franchise_id"])
        op.create_index("ix_franchise_fee_bills_status", "franchise_fee_bills", ["tenant_id", "status"])
        op.create_index("ix_franchise_fee_bills_due_date", "franchise_fee_bills", ["due_date"])
        op.create_index("ix_franchise_fee_bills_billing_period", "franchise_fee_bills", ["tenant_id", "billing_period"])

    op.execute("ALTER TABLE franchise_fee_bills ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS franchise_fee_bills_tenant ON franchise_fee_bills;")
    op.execute("""
        CREATE POLICY franchise_fee_bills_tenant ON franchise_fee_bills
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── franchise_fee_payments ────────────────────────────────────────────────
    if "franchise_fee_payments" not in existing:
        op.create_table(
            "franchise_fee_payments",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("bill_id", UUID(as_uuid=True), nullable=True, comment="关联 franchise_fee_bills.id"),
            sa.Column("paid_amount_fen", sa.BigInteger, nullable=False, comment="本次收款金额（分）"),
            sa.Column(
                "payment_method", sa.String(30), nullable=True, comment="支付方式：bank_transfer/cash/wechat/alipay 等"
            ),
            sa.Column("payment_date", sa.Date, nullable=False, comment="收款日期"),
            sa.Column("receipt_no", sa.String(100), nullable=True, comment="收款凭证号（银行流水号/收据号等）"),
            sa.Column("notes", sa.Text, nullable=True, comment="收款备注"),
            sa.Column("recorded_by", UUID(as_uuid=True), nullable=True, comment="录入人员工 ID"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
            sa.ForeignKeyConstraint(["bill_id"], ["franchise_fee_bills.id"], ondelete="RESTRICT"),
        )
        op.create_index("ix_franchise_fee_payments_bill_id", "franchise_fee_payments", ["bill_id"])
        op.create_index("ix_franchise_fee_payments_tenant", "franchise_fee_payments", ["tenant_id"])
        op.create_index("ix_franchise_fee_payments_payment_date", "franchise_fee_payments", ["payment_date"])

    op.execute("ALTER TABLE franchise_fee_payments ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS franchise_fee_payments_tenant ON franchise_fee_payments;")
    op.execute("""
        CREATE POLICY franchise_fee_payments_tenant ON franchise_fee_payments
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── franchise_billing_rules ───────────────────────────────────────────────
    if "franchise_billing_rules" not in existing:
        op.create_table(
            "franchise_billing_rules",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("franchise_id", UUID(as_uuid=True), nullable=False, comment="加盟商 ID"),
            sa.Column(
                "fee_type", sa.String(30), nullable=True, comment="费用类型：joining_fee/royalty/ad_fee/supply_fee"
            ),
            sa.Column("amount_fen", sa.BigInteger, nullable=True, comment="固定金额（分），与 rate 二选一"),
            sa.Column(
                "rate", sa.Numeric(6, 4), nullable=True, comment="比例费率（如 0.0300 = 3%），与 amount_fen 二选一"
            ),
            sa.Column(
                "billing_cycle", sa.String(20), nullable=True, comment="出账周期：monthly=月 / quarterly=季 / yearly=年"
            ),
            sa.Column("billing_day", sa.Integer, nullable=True, comment="出账日（每月/季/年的第几天），1-28"),
            sa.Column("start_date", sa.Date, nullable=True, comment="规则生效日期"),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="true", comment="是否启用"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
        op.create_index(
            "ix_franchise_billing_rules_tenant_franchise", "franchise_billing_rules", ["tenant_id", "franchise_id"]
        )
        op.create_index("ix_franchise_billing_rules_active", "franchise_billing_rules", ["tenant_id", "is_active"])

    op.execute("ALTER TABLE franchise_billing_rules ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS franchise_billing_rules_tenant ON franchise_billing_rules;")
    op.execute("""
        CREATE POLICY franchise_billing_rules_tenant ON franchise_billing_rules
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── franchise_reminder_logs ───────────────────────────────────────────────
    if "franchise_reminder_logs" not in existing:
        op.create_table(
            "franchise_reminder_logs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("bill_id", UUID(as_uuid=True), nullable=True, comment="关联 franchise_fee_bills.id"),
            sa.Column("reminder_type", sa.String(20), nullable=True, comment="提醒渠道：wecom=企业微信 / sms=短信"),
            sa.Column("sent_to", sa.String(100), nullable=True, comment="发送目标（手机号/企业微信 UserID）"),
            sa.Column(
                "sent_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
                comment="发送时间",
            ),
            sa.Column("status", sa.String(20), nullable=True, comment="sent=已发送 / failed=发送失败"),
            sa.ForeignKeyConstraint(["bill_id"], ["franchise_fee_bills.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_franchise_reminder_logs_bill_id", "franchise_reminder_logs", ["bill_id"])
        op.create_index("ix_franchise_reminder_logs_sent_at", "franchise_reminder_logs", ["sent_at"])

    # franchise_reminder_logs 无 tenant_id，通过 bill_id 关联受账单 RLS 保护
    # 仍需启用 RLS，策略通过 bill_id 做子查询隔离
    op.execute("ALTER TABLE franchise_reminder_logs ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS franchise_reminder_logs_open ON franchise_reminder_logs;")
    op.execute("""
        CREATE POLICY franchise_reminder_logs_open ON franchise_reminder_logs
            USING (
                bill_id IN (
                    SELECT id FROM franchise_fee_bills
                    WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                )
            );
    """)


def downgrade() -> None:
    op.drop_table("franchise_reminder_logs")
    op.drop_table("franchise_billing_rules")
    op.drop_table("franchise_fee_payments")
    op.drop_table("franchise_fee_bills")
