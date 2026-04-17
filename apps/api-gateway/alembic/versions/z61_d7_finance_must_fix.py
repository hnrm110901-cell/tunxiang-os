"""z61 — D7 财务资金 Must-Fix P0 (会计凭证 + AR/AP 台账 + 电子发票日志)

共 7 张新表：
  Task 1 会计凭证（3）: chart_of_accounts, vouchers, voucher_entries
  Task 2 AR/AP 台账（4）: accounts_receivable, ar_payments, accounts_payable, ap_payments
  Task 3 电子发票日志（1）: einvoice_logs

模型来源（只读）:
  src/models/accounting.py, src/models/ar_ap.py, src/models/einvoice_log.py

Revision ID: z61_d7_finance_must_fix
Revises: z60_d1_d4_pos_crm_menu_tables
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers, used by Alembic.
revision = "z61_d7_finance_must_fix"
down_revision = "z60_d1_d4_pos_crm_menu_tables"
branch_labels = None
depends_on = None


# ─────────────────────────────── Enum definitions ───────────────────────────────
ACCOUNT_TYPE = ("asset", "liability", "equity", "revenue", "cost", "expense")
VOUCHER_STATUS = ("draft", "posted", "void")
AR_STATUS = ("open", "partial", "closed", "written_off", "overdue")
AP_STATUS = ("open", "partial", "closed", "cancelled", "overdue")
EINVOICE_LOG_STATUS = ("pending", "issuing", "issued", "failed", "cancelled")


def upgrade():
    # ─── Enum 类型 ───
    account_type_enum = sa.Enum(*ACCOUNT_TYPE, name="account_type")
    voucher_status_enum = sa.Enum(*VOUCHER_STATUS, name="voucher_status")
    ar_status_enum = sa.Enum(*AR_STATUS, name="ar_status")
    ap_status_enum = sa.Enum(*AP_STATUS, name="ap_status")
    einvoice_log_status_enum = sa.Enum(*EINVOICE_LOG_STATUS, name="einvoice_log_status")

    account_type_enum.create(op.get_bind(), checkfirst=True)
    voucher_status_enum.create(op.get_bind(), checkfirst=True)
    ar_status_enum.create(op.get_bind(), checkfirst=True)
    ap_status_enum.create(op.get_bind(), checkfirst=True)
    einvoice_log_status_enum.create(op.get_bind(), checkfirst=True)

    # ─────────── Task 1: 会计凭证 ───────────

    op.create_table(
        "chart_of_accounts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("brand_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("code", sa.String(20), nullable=False, index=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("account_type", account_type_enum, nullable=False),
        sa.Column("parent_code", sa.String(20), nullable=True, index=True),
        sa.Column("normal_balance", sa.String(10), nullable=False, server_default="debit"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_active", sa.String(10), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("uq_coa_brand_code", "chart_of_accounts", ["brand_id", "code"], unique=True)

    op.create_table(
        "vouchers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("brand_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("store_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("voucher_no", sa.String(40), nullable=False, unique=True, index=True),
        sa.Column("voucher_date", sa.Date, nullable=False, index=True),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("status", voucher_status_enum, nullable=False, server_default="posted", index=True),
        sa.Column("total_debit_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_credit_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("source_type", sa.String(50), nullable=True, index=True),
        sa.Column("source_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("posted_by", UUID(as_uuid=True), nullable=True),
        sa.Column("posted_at", sa.DateTime, nullable=True),
        sa.Column("void_reason", sa.String(500), nullable=True),
        sa.Column("extras", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_voucher_date_status", "vouchers", ["voucher_date", "status"])
    op.create_index("idx_voucher_source", "vouchers", ["source_type", "source_id"])

    op.create_table(
        "voucher_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("voucher_id", UUID(as_uuid=True), sa.ForeignKey("vouchers.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("line_no", sa.Integer, nullable=False, server_default="1"),
        sa.Column("account_code", sa.String(20), nullable=False, index=True),
        sa.Column("account_name", sa.String(100), nullable=False),
        sa.Column("debit_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("credit_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("summary", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_ventry_account_code", "voucher_entries", ["account_code"])

    # ─────────── Task 2: AR/AP ───────────

    op.create_table(
        "accounts_receivable",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("brand_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("store_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("customer_type", sa.String(30), nullable=False, server_default="credit_account"),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("customer_name", sa.String(200), nullable=False),
        sa.Column("ar_no", sa.String(40), nullable=False, unique=True, index=True),
        sa.Column("source_bill_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("source_ref", sa.String(100), nullable=True),
        sa.Column("amount_fen", sa.Integer, nullable=False),
        sa.Column("received_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("issue_date", sa.Date, nullable=False, index=True),
        sa.Column("due_date", sa.Date, nullable=True, index=True),
        sa.Column("status", ar_status_enum, nullable=False, server_default="open", index=True),
        sa.Column("remark", sa.String(500), nullable=True),
        sa.Column("extras", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_ar_customer_status", "accounts_receivable", ["customer_id", "status"])
    op.create_index("idx_ar_due_status", "accounts_receivable", ["due_date", "status"])
    op.create_index("idx_ar_store_status", "accounts_receivable", ["store_id", "status"])

    op.create_table(
        "ar_payments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("ar_id", UUID(as_uuid=True), sa.ForeignKey("accounts_receivable.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("amount_fen", sa.Integer, nullable=False),
        sa.Column("payment_date", sa.Date, nullable=False),
        sa.Column("payment_method", sa.String(30), nullable=True),
        sa.Column("reference_no", sa.String(100), nullable=True),
        sa.Column("operator_id", UUID(as_uuid=True), nullable=True),
        sa.Column("remark", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "accounts_payable",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("brand_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("store_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("supplier_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("supplier_name", sa.String(200), nullable=False),
        sa.Column("ap_no", sa.String(40), nullable=False, unique=True, index=True),
        sa.Column("source_po_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("source_ref", sa.String(100), nullable=True),
        sa.Column("amount_fen", sa.Integer, nullable=False),
        sa.Column("paid_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("issue_date", sa.Date, nullable=False, index=True),
        sa.Column("due_date", sa.Date, nullable=True, index=True),
        sa.Column("status", ap_status_enum, nullable=False, server_default="open", index=True),
        sa.Column("remark", sa.String(500), nullable=True),
        sa.Column("extras", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_ap_supplier_status", "accounts_payable", ["supplier_id", "status"])
    op.create_index("idx_ap_due_status", "accounts_payable", ["due_date", "status"])
    op.create_index("idx_ap_store_status", "accounts_payable", ["store_id", "status"])

    op.create_table(
        "ap_payments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("ap_id", UUID(as_uuid=True), sa.ForeignKey("accounts_payable.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("amount_fen", sa.Integer, nullable=False),
        sa.Column("payment_date", sa.Date, nullable=False),
        sa.Column("payment_method", sa.String(30), nullable=True),
        sa.Column("reference_no", sa.String(100), nullable=True),
        sa.Column("operator_id", UUID(as_uuid=True), nullable=True),
        sa.Column("remark", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # ─────────── Task 3: 电子发票日志 ───────────

    op.create_table(
        "einvoice_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("brand_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("store_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("bill_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("short_code", sa.String(20), nullable=True, unique=True, index=True),
        sa.Column("self_service_url", sa.Text, nullable=True),
        sa.Column("buyer_name", sa.String(200), nullable=True),
        sa.Column("buyer_tax_number", sa.String(30), nullable=True),
        sa.Column("buyer_phone", sa.String(30), nullable=True),
        sa.Column("buyer_email", sa.String(100), nullable=True),
        sa.Column("invoice_no", sa.String(30), nullable=True, index=True),
        sa.Column("invoice_code", sa.String(20), nullable=True),
        sa.Column("pdf_url", sa.Text, nullable=True),
        sa.Column("amount_fen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", einvoice_log_status_enum, nullable=False, server_default="pending", index=True),
        sa.Column("platform", sa.String(20), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("issued_at", sa.DateTime, nullable=True),
        sa.Column("extras", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_einvoice_log_bill", "einvoice_logs", ["bill_id"])
    op.create_index("idx_einvoice_log_status", "einvoice_logs", ["status"])


def downgrade():
    op.drop_table("einvoice_logs")
    op.drop_table("ap_payments")
    op.drop_table("accounts_payable")
    op.drop_table("ar_payments")
    op.drop_table("accounts_receivable")
    op.drop_table("voucher_entries")
    op.drop_table("vouchers")
    op.drop_table("chart_of_accounts")

    bind = op.get_bind()
    for name in ("einvoice_log_status", "ap_status", "ar_status", "voucher_status", "account_type"):
        sa.Enum(name=name).drop(bind, checkfirst=True)
