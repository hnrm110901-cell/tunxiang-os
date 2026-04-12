"""加盟合同收费 + 供应商EDI对接

Revision: v217
Tables:
  - franchise_contracts       加盟合同主表
  - franchise_fee_records     加盟收费记录
  - edi_orders                EDI电子采购订单
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v217"
down_revision = "v216"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()

    # ── 加盟合同主表 ──
    if 'franchise_contracts' not in existing:
        op.create_table(
            "franchise_contracts",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("contract_no", sa.VARCHAR(50), nullable=False, comment="合同编号 FC-YYYYMM-XXXX"),
            sa.Column("contract_type", sa.VARCHAR(20), nullable=False,
                      comment="initial/renewal/amendment"),
            sa.Column("franchisee_id", sa.VARCHAR(100), nullable=False, comment="加盟商ID"),
            sa.Column("franchisee_name", sa.VARCHAR(200), server_default="", comment="加盟商名称"),
            sa.Column("sign_date", sa.DATE, nullable=False),
            sa.Column("start_date", sa.DATE, nullable=False),
            sa.Column("end_date", sa.DATE, nullable=False),
            sa.Column("contract_amount_fen", sa.BIGINT, server_default="0", comment="合同金额(分)"),
            sa.Column("file_url", sa.TEXT, nullable=True, comment="合同文件URL"),
            sa.Column("status", sa.VARCHAR(20), server_default="active",
                      comment="active/expired/terminated"),
            sa.Column("alert_days_before", sa.INTEGER, server_default="30",
                      comment="到期提醒提前天数"),
            sa.Column("notes", sa.TEXT, nullable=True),
            sa.Column("created_by", sa.VARCHAR(100), nullable=True),
            sa.Column("is_deleted", sa.BOOLEAN, server_default="false", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
        )
        op.create_index("ix_franchise_contracts_tenant_status",
                        "franchise_contracts", ["tenant_id", "status"])
        op.create_index("ix_franchise_contracts_franchisee",
                        "franchise_contracts", ["tenant_id", "franchisee_id"])
        op.create_index("ix_franchise_contracts_end_date",
                        "franchise_contracts", ["tenant_id", "end_date"])
    op.execute("ALTER TABLE franchise_contracts ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'franchise_contracts'
                AND policyname = 'fc_tenant_isolation'
            ) THEN
                EXECUTE 'CREATE POLICY fc_tenant_isolation ON franchise_contracts
                    USING (tenant_id = current_setting(''app.tenant_id'')::uuid)';
            END IF;
        END$$;
    """)

    # ── 加盟收费记录 ──
    op.create_table(
        "franchise_fee_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contract_id", postgresql.UUID(as_uuid=True), nullable=True,
                  comment="关联合同ID"),
        sa.Column("franchisee_id", sa.VARCHAR(100), nullable=False),
        sa.Column("franchisee_name", sa.VARCHAR(200), server_default=""),
        sa.Column("fee_type", sa.VARCHAR(30), nullable=False,
                  comment="joining_fee/royalty/management_fee/marketing_fee/brand_fee/deposit"),
        sa.Column("period_start", sa.DATE, nullable=True, comment="计费周期开始"),
        sa.Column("period_end", sa.DATE, nullable=True, comment="计费周期结束"),
        sa.Column("amount_fen", sa.BIGINT, nullable=False, comment="应收金额(分)"),
        sa.Column("paid_fen", sa.BIGINT, server_default="0", comment="已收金额(分)"),
        sa.Column("due_date", sa.DATE, nullable=True, comment="应收日期"),
        sa.Column("status", sa.VARCHAR(20), server_default="unpaid",
                  comment="unpaid/partial/paid/overdue/waived"),
        sa.Column("receipt_no", sa.VARCHAR(50), nullable=True),
        sa.Column("receipt_url", sa.TEXT, nullable=True),
        sa.Column("notes", sa.TEXT, nullable=True),
        sa.Column("is_deleted", sa.BOOLEAN, server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_franchise_fee_records_tenant_status",
                    "franchise_fee_records", ["tenant_id", "status"])
    op.create_index("ix_franchise_fee_records_contract",
                    "franchise_fee_records", ["tenant_id", "contract_id"])
    op.create_index("ix_franchise_fee_records_franchisee",
                    "franchise_fee_records", ["tenant_id", "franchisee_id"])
    op.create_index("ix_franchise_fee_records_due_date",
                    "franchise_fee_records", ["tenant_id", "due_date"])

    op.execute("ALTER TABLE franchise_fee_records ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY ffr_tenant_isolation ON franchise_fee_records
        USING (tenant_id = current_setting('app.tenant_id')::uuid)
    """)

    # ── EDI电子采购订单 ──
    op.create_table(
        "edi_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("edi_no", sa.VARCHAR(50), nullable=False, comment="EDI订单编号"),
        sa.Column("po_id", postgresql.UUID(as_uuid=True), nullable=True,
                  comment="关联采购订单ID"),
        sa.Column("supplier_id", sa.VARCHAR(100), nullable=False),
        sa.Column("supplier_name", sa.VARCHAR(200), server_default=""),
        sa.Column("store_id", sa.VARCHAR(100), nullable=False),
        sa.Column("store_name", sa.VARCHAR(200), server_default=""),
        sa.Column("items", postgresql.JSONB, nullable=False, server_default="[]",
                  comment="[{ingredient_id, name, qty, unit, unit_price_fen}]"),
        sa.Column("total_amount_fen", sa.BIGINT, server_default="0"),
        sa.Column("status", sa.VARCHAR(30), server_default="pushed",
                  comment="pushed/supplier_confirmed/shipped/received/cancelled"),
        sa.Column("pushed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supplier_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tracking_no", sa.VARCHAR(100), nullable=True),
        sa.Column("delivery_notes", sa.TEXT, nullable=True),
        sa.Column("receive_notes", sa.TEXT, nullable=True),
        sa.Column("notes", sa.TEXT, nullable=True),
        sa.Column("is_deleted", sa.BOOLEAN, server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_edi_orders_tenant_status",
                    "edi_orders", ["tenant_id", "status"])
    op.create_index("ix_edi_orders_supplier",
                    "edi_orders", ["tenant_id", "supplier_id"])
    op.create_index("ix_edi_orders_store",
                    "edi_orders", ["tenant_id", "store_id"])
    op.create_index("ix_edi_orders_po",
                    "edi_orders", ["tenant_id", "po_id"])

    op.execute("ALTER TABLE edi_orders ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY edi_tenant_isolation ON edi_orders
        USING (tenant_id = current_setting('app.tenant_id')::uuid)
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS edi_tenant_isolation ON edi_orders")
    op.drop_table("edi_orders")
    op.execute("DROP POLICY IF EXISTS ffr_tenant_isolation ON franchise_fee_records")
    op.drop_table("franchise_fee_records")
    op.execute("DROP POLICY IF EXISTS fc_tenant_isolation ON franchise_contracts")
    op.drop_table("franchise_contracts")
