"""电子发票全链路 — 开票/红冲/重开/状态同步

第200个迁移版本里程碑。
新建 e_invoices 表，支持普票/红冲/更正全状态机，金额全部用分（整数），
启用 RLS 租户隔离（使用 app.tenant_id，与平台规范一致）。

Revision ID: v200
Revises: v199
Create Date: 2026-04-07
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "v200"
down_revision = "v199"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── e_invoices — 电子发票主表 ────────────────────────────────────────────
    op.create_table(
        "e_invoices",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        # 关联订单（红冲时可为 NULL）
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True),
        # 发票类型：normal=增值税普票 / red_note=红冲票 / correction=更正票
        sa.Column(
            "invoice_type",
            sa.VARCHAR(20),
            nullable=False,
            comment="normal/red_note/correction",
        ),
        # 第三方平台返回的发票号码与代码（诺诺/税局）
        sa.Column("invoice_no", sa.VARCHAR(50), nullable=True),
        sa.Column("invoice_code", sa.VARCHAR(20), nullable=True),
        # 状态机：pending → issuing → issued | failed → (reissue) → ...
        #         issued → red_noted（红冲后） | cancelled
        sa.Column(
            "status",
            sa.VARCHAR(20),
            nullable=False,
            server_default="pending",
            comment="pending/issuing/issued/failed/cancelled/red_noted",
        ),
        # 购方信息
        sa.Column("buyer_name", sa.VARCHAR(100), nullable=True),
        sa.Column("buyer_tax_no", sa.VARCHAR(30), nullable=True),
        sa.Column("buyer_email", sa.VARCHAR(100), nullable=True),
        # 销方信息（从租户配置填充）
        sa.Column("seller_name", sa.VARCHAR(100), nullable=True),
        sa.Column("seller_tax_no", sa.VARCHAR(30), nullable=True),
        # 金额字段（全部用分，整数，避免浮点误差）
        sa.Column(
            "total_amount_fen",
            sa.BigInteger(),
            nullable=False,
            comment="价税合计，单位：分",
        ),
        sa.Column(
            "tax_amount_fen",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
            comment="税额，单位：分",
        ),
        sa.Column(
            "tax_rate",
            sa.Numeric(5, 4),
            nullable=False,
            server_default="0.0600",
            comment="税率，如 0.0600 = 6%",
        ),
        # 发票明细 JSON：[{name, qty, unit_price_fen, amount_fen, tax_rate}]
        sa.Column(
            "items",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
            comment="发票明细列表",
        ),
        # 开票结果
        sa.Column("issue_time", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("pdf_url", sa.Text(), nullable=True),
        # 红冲时关联原票 ID
        sa.Column(
            "original_invoice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("e_invoices.id", ondelete="SET NULL"),
            nullable=True,
            comment="红冲时关联的原始发票",
        ),
        # 失败原因 / 重试次数
        sa.Column("failed_reason", sa.Text(), nullable=True),
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        # 第三方请求 ID（幂等：相同 order_id + buyer_tax_no 的重复申请复用）
        sa.Column(
            "third_party_req_id",
            sa.VARCHAR(100),
            nullable=True,
            unique=True,
            comment="第三方平台请求ID，用于幂等去重",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    # ─── 索引 ─────────────────────────────────────────────────────────────────

    op.create_index("idx_e_invoices_tenant", "e_invoices", ["tenant_id"])
    op.create_index("idx_e_invoices_order", "e_invoices", ["order_id"])
    op.create_index(
        "idx_e_invoices_status",
        "e_invoices",
        ["tenant_id", "status"],
    )
    op.create_index(
        "idx_e_invoices_invoice_no",
        "e_invoices",
        ["invoice_no"],
        postgresql_where=sa.text("invoice_no IS NOT NULL"),
    )
    op.create_index(
        "idx_e_invoices_created_at",
        "e_invoices",
        ["tenant_id", "created_at"],
    )

    # ─── updated_at 自动更新触发器 ────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION update_e_invoices_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_e_invoices_updated_at
        BEFORE UPDATE ON e_invoices
        FOR EACH ROW EXECUTE FUNCTION update_e_invoices_updated_at()
    """)

    # ─── RLS — 租户隔离（使用 app.tenant_id，与平台其他表一致）─────────────

    op.execute("ALTER TABLE e_invoices ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY e_invoices_tenant_isolation ON e_invoices
        USING (tenant_id = (current_setting('app.tenant_id', true)::UUID))
        WITH CHECK (tenant_id = (current_setting('app.tenant_id', true)::UUID))
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_e_invoices_updated_at ON e_invoices")
    op.execute("DROP FUNCTION IF EXISTS update_e_invoices_updated_at()")
    op.execute("DROP POLICY IF EXISTS e_invoices_tenant_isolation ON e_invoices")

    op.drop_index("idx_e_invoices_created_at", table_name="e_invoices")
    op.drop_index("idx_e_invoices_invoice_no", table_name="e_invoices")
    op.drop_index("idx_e_invoices_status", table_name="e_invoices")
    op.drop_index("idx_e_invoices_order", table_name="e_invoices")
    op.drop_index("idx_e_invoices_tenant", table_name="e_invoices")

    op.drop_table("e_invoices")
