"""v254 — 顾客开票申请表（invoice_requests）

顾客餐后扫码填写抬头，提交开票申请；税控平台处理后写回状态。
此表独立于 v238 的费控报销 invoices 表（场景不同）。

Revision ID: v254
Revises: v253
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "v254"
down_revision = "v253"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing_tables = sa.inspect(conn).get_table_names()

    if "invoice_requests" not in existing_tables:
        op.create_table(
            "invoice_requests",
            sa.Column(
                "id",
                sa.UUID,
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
                comment="主键",
            ),
            sa.Column("tenant_id", sa.UUID, nullable=False, comment="租户ID（RLS）"),
            sa.Column(
                "order_id",
                sa.Text,
                nullable=False,
                comment="顾客订单ID，文本类型避免外键约束",
            ),
            sa.Column(
                "invoice_no",
                sa.String(50),
                nullable=False,
                comment="发票编号，如 INV20260413XXXXXX",
            ),
            sa.Column(
                "invoice_type",
                sa.String(20),
                nullable=False,
                server_default=sa.text("'electronic'"),
                comment="发票类型：electronic / paper / vat_special",
            ),
            sa.Column("buyer_name", sa.String(200), nullable=True, comment="购方名称"),
            sa.Column("buyer_tax_no", sa.String(30), nullable=True, comment="购方税号"),
            sa.Column("buyer_address", sa.Text, nullable=True, comment="购方地址"),
            sa.Column("buyer_phone", sa.String(50), nullable=True, comment="购方电话"),
            sa.Column("buyer_bank_name", sa.String(100), nullable=True, comment="购方开户行"),
            sa.Column("buyer_bank_account", sa.String(100), nullable=True, comment="购方银行账号"),
            sa.Column("buyer_email", sa.String(200), nullable=True, comment="电子发票接收邮箱"),
            sa.Column(
                "amount_fen",
                sa.BigInteger,
                nullable=False,
                server_default=sa.text("0"),
                comment="金额（分）",
            ),
            sa.Column(
                "items",
                sa.JSON,
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
                comment="发票明细行 JSONB",
            ),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default=sa.text("'pending'"),
                comment="状态：pending / submitted / issued / failed / cancelled",
            ),
            sa.Column(
                "tax_platform_code",
                sa.String(100),
                nullable=True,
                comment="税控平台返回的发票代码",
            ),
            sa.Column("pdf_url", sa.Text, nullable=True, comment="电子发票 PDF 链接"),
            sa.Column("error_message", sa.Text, nullable=True, comment="失败原因"),
            sa.Column(
                "submitted_at",
                sa.TIMESTAMP(timezone=True),
                nullable=True,
                comment="提交税控平台时间",
            ),
            sa.Column(
                "issued_at",
                sa.TIMESTAMP(timezone=True),
                nullable=True,
                comment="开票成功时间",
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("NOW()"),
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("NOW()"),
            ),
            sa.Column(
                "is_deleted",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("FALSE"),
            ),
        )

        op.create_index("ix_invoice_requests_tenant", "invoice_requests", ["tenant_id"])
        op.create_index(
            "ix_invoice_requests_tenant_status",
            "invoice_requests",
            ["tenant_id", "status"],
        )
        op.create_index("ix_invoice_requests_order", "invoice_requests", ["order_id"])

        op.execute("ALTER TABLE invoice_requests ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE invoice_requests FORCE ROW LEVEL SECURITY")
        op.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE tablename = 'invoice_requests'
                      AND policyname = 'ir_tenant'
                ) THEN
                    EXECUTE $pol$
                        CREATE POLICY ir_tenant ON invoice_requests
                        USING (
                            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                        )
                    $pol$;
                END IF;
            END;
            $$
        """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS invoice_requests CASCADE")
