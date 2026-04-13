"""vat ledger for enterprise tax management

Revision ID: v203
Revises: v202
Create Date: 2026-04-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, NUMERIC

revision = 'v203'
down_revision = 'v202'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()


    # 销项税台账（开出的发票）

    if 'vat_output_records' not in existing:
        op.create_table(
            'vat_output_records',
            sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
            sa.Column('tenant_id', UUID(as_uuid=True), nullable=False),
            sa.Column('store_id', UUID(as_uuid=True), nullable=True),
            sa.Column('invoice_id', UUID(as_uuid=True), nullable=True),   # 关联 e_invoices 表
            sa.Column('order_id', UUID(as_uuid=True), nullable=True),
            sa.Column('period_month', sa.String(7), nullable=False),       # 2026-04 格式
            sa.Column('tax_code', sa.String(20), nullable=False),          # 税收分类编码
            sa.Column('tax_rate', NUMERIC(5, 4), nullable=False),          # 0.06/0.09/0.13
            sa.Column('amount_excl_tax_fen', sa.BigInteger(), nullable=False),  # 不含税金额（分）
            sa.Column('tax_amount_fen', sa.BigInteger(), nullable=False),    # 税额（分）
            sa.Column('amount_incl_tax_fen', sa.BigInteger(), nullable=False),  # 含税金额（分）
            sa.Column('buyer_name', sa.String(100), nullable=True),
            sa.Column('buyer_tax_id', sa.String(20), nullable=True),
            sa.Column('invoice_date', sa.Date(), nullable=False),
            sa.Column('status', sa.String(20), nullable=False, server_default='normal'),  # normal/voided/red_correction
            sa.Column('nuonuo_order_id', sa.String(64), nullable=True),    # 诺诺平台流水号
            sa.Column('extra', JSONB(), nullable=True),
            sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()')),
            sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()')),
            sa.Column('is_deleted', sa.Boolean(), server_default='false'),
        )
        op.create_index('ix_vat_output_tenant_period', 'vat_output_records', ['tenant_id', 'period_month'])
        op.create_index('ix_vat_output_invoice', 'vat_output_records', ['invoice_id'])
        op.execute("""
            ALTER TABLE vat_output_records ENABLE ROW LEVEL SECURITY;
            CREATE POLICY vat_output_records_rls ON vat_output_records
                USING (tenant_id = current_setting('app.tenant_id', true)::UUID)
                WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::UUID);
        """)

        # 进项税台账（收到的发票/抵扣）

    if 'vat_input_records' not in existing:
        op.create_table(
            'vat_input_records',
            sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
            sa.Column('tenant_id', UUID(as_uuid=True), nullable=False),
            sa.Column('store_id', UUID(as_uuid=True), nullable=True),
            sa.Column('purchase_order_id', UUID(as_uuid=True), nullable=True),
            sa.Column('period_month', sa.String(7), nullable=False),
            sa.Column('tax_code', sa.String(20), nullable=False),
            sa.Column('tax_rate', NUMERIC(5, 4), nullable=False),
            sa.Column('amount_excl_tax_fen', sa.BigInteger(), nullable=False),
            sa.Column('tax_amount_fen', sa.BigInteger(), nullable=False),
            sa.Column('amount_incl_tax_fen', sa.BigInteger(), nullable=False),
            sa.Column('seller_name', sa.String(100), nullable=True),
            sa.Column('seller_tax_id', sa.String(20), nullable=True),
            sa.Column('invoice_code', sa.String(20), nullable=True),
            sa.Column('invoice_number', sa.String(10), nullable=True),
            sa.Column('invoice_date', sa.Date(), nullable=False),
            sa.Column('deduction_status', sa.String(20), nullable=False, server_default='pending'),  # pending/deducted/rejected
            sa.Column('pl_account_code', sa.String(20), nullable=True),    # P&L 科目代码
            sa.Column('extra', JSONB(), nullable=True),
            sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()')),
            sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()')),
            sa.Column('is_deleted', sa.Boolean(), server_default='false'),
        )
        op.create_index('ix_vat_input_tenant_period', 'vat_input_records', ['tenant_id', 'period_month'])
        op.execute("""
            ALTER TABLE vat_input_records ENABLE ROW LEVEL SECURITY;
            CREATE POLICY vat_input_records_rls ON vat_input_records
                USING (tenant_id = current_setting('app.tenant_id', true)::UUID)
                WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::UUID);
        """)

        # P&L 科目映射

    if 'pl_account_mappings' not in existing:
        op.create_table(
            'pl_account_mappings',
            sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
            sa.Column('tenant_id', UUID(as_uuid=True), nullable=False),
            sa.Column('tax_code', sa.String(20), nullable=False),
            sa.Column('pl_account_code', sa.String(20), nullable=False),
            sa.Column('pl_account_name', sa.String(100), nullable=False),
            sa.Column('account_type', sa.String(20), nullable=False),  # revenue/cost/tax_payable
            sa.Column('is_active', sa.Boolean(), server_default='true'),
            sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()')),
        )
        op.create_index(
            'ix_pl_account_mappings_unique',
            'pl_account_mappings',
            ['tenant_id', 'tax_code'],
            unique=True,
        )
        op.execute("""
            ALTER TABLE pl_account_mappings ENABLE ROW LEVEL SECURITY;
            CREATE POLICY pl_account_mappings_rls ON pl_account_mappings
                USING (tenant_id = current_setting('app.tenant_id', true)::UUID);
        """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS pl_account_mappings_rls ON pl_account_mappings")
    op.execute("DROP POLICY IF EXISTS vat_input_records_rls ON vat_input_records")
    op.execute("DROP POLICY IF EXISTS vat_output_records_rls ON vat_output_records")

    op.drop_index('ix_pl_account_mappings_unique', table_name='pl_account_mappings')
    op.drop_index('ix_vat_input_tenant_period', table_name='vat_input_records')
    op.drop_index('ix_vat_output_invoice', table_name='vat_output_records')
    op.drop_index('ix_vat_output_tenant_period', table_name='vat_output_records')

    op.drop_table('pl_account_mappings')
    op.drop_table('vat_input_records')
    op.drop_table('vat_output_records')
