"""供应链采购付款联动：付款单 + 付款条目 + 对账记录
Tables: procurement_payments, procurement_payment_items, procurement_reconciliations
Sprint: P1-S4（供应链采购付款联动模块）

设计原则：
  - 付款单与 tx-supply 采购订单深度打通（purchase_order_id 唯一键）
  - 幂等保护：同一 purchase_order_id 只创建一张付款单
  - 对账记录：比较付款单金额 vs 发票总金额，自动计算差异

Revision ID: v240
Revises: v239
Create Date: 2026-04-12
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import NUMERIC, UUID

revision = "v240b"
down_revision = "v240"
branch_labels = None
depends_on = None

# 标准安全 RLS 条件（NULLIF 保护，与 v231 规范一致）
_RLS_COND = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()

    # ------------------------------------------------------------------
    # 表1：procurement_payments（采购付款单）
    # ------------------------------------------------------------------

    if "procurement_payments" not in existing:
        op.create_table(
            "procurement_payments",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"), nullable=False
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "purchase_order_id",
                UUID(as_uuid=True),
                nullable=False,
                comment="tx-supply 的采购订单ID（唯一键，幂等保护）",
            ),
            sa.Column(
                "purchase_order_no", sa.String(64), nullable=True, comment="采购单号（冗余存储，避免跨服务查询）"
            ),
            sa.Column("supplier_id", UUID(as_uuid=True), nullable=True, comment="供应商ID"),
            sa.Column("supplier_name", sa.String(200), nullable=True, comment="供应商名称（冗余存储）"),
            sa.Column(
                "payment_type",
                sa.String(32),
                nullable=False,
                server_default="purchase",
                comment="付款类型：purchase（采购）/ deposit（预付款）/ final（尾款）",
            ),
            sa.Column(
                "total_amount", sa.BigInteger(), nullable=False, comment="总金额，单位：分(fen)，展示时除以100转元"
            ),
            sa.Column(
                "paid_amount", sa.BigInteger(), nullable=False, server_default="0", comment="已付金额，单位：分(fen)"
            ),
            sa.Column(
                "status",
                sa.String(32),
                nullable=False,
                server_default="pending",
                comment="状态：pending / approved / paid / cancelled",
            ),
            sa.Column("due_date", sa.Date(), nullable=True, comment="付款到期日"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by", UUID(as_uuid=True), nullable=True, comment="创建人员工ID"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=True, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True, server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        )

        # 索引
        op.create_index(
            "ix_procurement_payments_tenant_status",
            "procurement_payments",
            ["tenant_id", "status"],
        )
        op.create_index(
            "ix_procurement_payments_tenant_supplier",
            "procurement_payments",
            ["tenant_id", "supplier_id"],
            postgresql_where=sa.text("supplier_id IS NOT NULL"),
        )
        op.create_index(
            "ix_procurement_payments_tenant_created_at",
            "procurement_payments",
            ["tenant_id", sa.text("created_at DESC")],
        )
        op.create_index(
            "ix_procurement_payments_tenant_due_date",
            "procurement_payments",
            ["tenant_id", "due_date"],
            postgresql_where=sa.text("due_date IS NOT NULL AND is_deleted = false"),
        )
        # 幂等唯一键：同一租户的同一采购订单只允许一张付款单
        op.create_unique_constraint(
            "uq_procurement_payments_tenant_purchase_order",
            "procurement_payments",
            ["tenant_id", "purchase_order_id"],
        )

        # RLS
        op.execute("ALTER TABLE procurement_payments ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY procurement_payments_tenant_isolation
            ON procurement_payments
            USING ({_RLS_COND})
            """
        )

        # ------------------------------------------------------------------
        # 表2：procurement_payment_items（付款条目，与采购订单行对应）
        # ------------------------------------------------------------------

    if "procurement_payment_items" not in existing:
        op.create_table(
            "procurement_payment_items",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"), nullable=False
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("payment_id", UUID(as_uuid=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["payment_id"],
                ["procurement_payments.id"],
                name="fk_procurement_payment_items_payment_id",
                ondelete="CASCADE",
            ),
            sa.Column("order_item_id", UUID(as_uuid=True), nullable=True, comment="tx-supply 采购行ID"),
            sa.Column("product_name", sa.String(200), nullable=True, comment="商品名称（冗余存储）"),
            sa.Column("quantity", NUMERIC(12, 3), nullable=True, comment="数量"),
            sa.Column("unit_price", sa.BigInteger(), nullable=True, comment="单价，单位：分(fen)"),
            sa.Column("amount", sa.BigInteger(), nullable=False, comment="金额，单位：分(fen)"),
            sa.Column("invoice_id", UUID(as_uuid=True), nullable=True, comment="关联发票ID（发票匹配后填充）"),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=True, server_default=sa.text("now()")),
        )

        # 索引
        op.create_index(
            "ix_procurement_payment_items_tenant_payment",
            "procurement_payment_items",
            ["tenant_id", "payment_id"],
        )
        op.create_index(
            "ix_procurement_payment_items_tenant_invoice",
            "procurement_payment_items",
            ["tenant_id", "invoice_id"],
            postgresql_where=sa.text("invoice_id IS NOT NULL"),
        )

        # RLS
        op.execute("ALTER TABLE procurement_payment_items ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY procurement_payment_items_tenant_isolation
            ON procurement_payment_items
            USING ({_RLS_COND})
            """
        )

        # ------------------------------------------------------------------
        # 表3：procurement_reconciliations（对账记录）
        # ------------------------------------------------------------------

    if "procurement_reconciliations" not in existing:
        op.create_table(
            "procurement_reconciliations",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"), nullable=False
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("payment_id", UUID(as_uuid=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["payment_id"],
                ["procurement_payments.id"],
                name="fk_procurement_reconciliations_payment_id",
            ),
            sa.Column("reconciled_by", UUID(as_uuid=True), nullable=True, comment="对账操作人员工ID"),
            sa.Column(
                "reconciliation_status",
                sa.String(32),
                nullable=False,
                server_default="pending",
                comment="对账状态：pending / matched / discrepancy / resolved",
            ),
            sa.Column("payment_amount", sa.BigInteger(), nullable=True, comment="付款单金额，单位：分(fen)"),
            sa.Column("invoice_amount", sa.BigInteger(), nullable=True, comment="发票总金额，单位：分(fen)"),
            sa.Column(
                "discrepancy_amount",
                sa.BigInteger(),
                nullable=False,
                server_default="0",
                comment="差异金额（= payment_amount - invoice_amount），单位：分(fen)",
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("reconciled_at", sa.TIMESTAMP(timezone=True), nullable=True, comment="对账完成时间"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=True, server_default=sa.text("now()")),
        )

        # 索引
        op.create_index(
            "ix_procurement_reconciliations_tenant_payment",
            "procurement_reconciliations",
            ["tenant_id", "payment_id"],
        )
        op.create_index(
            "ix_procurement_reconciliations_tenant_status",
            "procurement_reconciliations",
            ["tenant_id", "reconciliation_status"],
        )
        op.create_index(
            "ix_procurement_reconciliations_tenant_created_at",
            "procurement_reconciliations",
            ["tenant_id", sa.text("created_at DESC")],
        )

        # RLS
        op.execute("ALTER TABLE procurement_reconciliations ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY procurement_reconciliations_tenant_isolation
            ON procurement_reconciliations
            USING ({_RLS_COND})
            """
        )


def downgrade() -> None:
    # 按依赖反向删除

    # procurement_reconciliations
    op.execute("DROP POLICY IF EXISTS procurement_reconciliations_tenant_isolation ON procurement_reconciliations")
    op.drop_table("procurement_reconciliations")

    # procurement_payment_items
    op.execute("DROP POLICY IF EXISTS procurement_payment_items_tenant_isolation ON procurement_payment_items")
    op.drop_table("procurement_payment_items")

    # procurement_payments
    op.execute("DROP POLICY IF EXISTS procurement_payments_tenant_isolation ON procurement_payments")
    op.drop_table("procurement_payments")
