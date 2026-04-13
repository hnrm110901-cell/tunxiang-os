"""加盟商合同+收费管理

Revision ID: v190
Revises: v189
Create Date: 2026-04-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'v190'
down_revision = 'v189'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()

    # ─── 1. franchise_contracts — 加盟合同 ───────────────────────────────────
    if 'franchise_contracts' not in existing:
        op.create_table(
            'franchise_contracts',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text('gen_random_uuid()')),
            sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('franchisee_id', postgresql.UUID(as_uuid=True), nullable=False,
                      comment='关联加盟商/门店'),
            sa.Column('contract_no', sa.VARCHAR(50), nullable=False,
                      comment='合同编号，唯一'),
            sa.Column('contract_type', sa.VARCHAR(30), nullable=False,
                      comment='initial/renewal/amendment：首签/续签/补充协议'),
            sa.Column('sign_date', sa.DATE(), nullable=False),
            sa.Column('start_date', sa.DATE(), nullable=False),
            sa.Column('end_date', sa.DATE(), nullable=False),
            sa.Column('contract_amount_fen', sa.BIGINT(), nullable=False, server_default='0',
                      comment='合同总金额（分）'),
            sa.Column('file_url', sa.Text(), nullable=True,
                      comment='合同文件OSS地址'),
            sa.Column('status', sa.VARCHAR(20), nullable=False, server_default='active',
                      comment='active/expired/terminated'),
            sa.Column('alert_days_before', sa.Integer(), nullable=False, server_default='30',
                      comment='到期提前N天预警'),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                      server_default=sa.text('NOW()'), nullable=False),
            sa.Column('updated_at', sa.TIMESTAMP(timezone=True),
                      server_default=sa.text('NOW()'), nullable=False),
            sa.UniqueConstraint('contract_no', name='uq_franchise_contracts_contract_no'),
        )
        op.create_index('idx_franchise_contracts_tenant_id',
                        'franchise_contracts', ['tenant_id'])
        op.create_index('idx_franchise_contracts_franchisee',
                        'franchise_contracts', ['tenant_id', 'franchisee_id'])
        op.create_index('idx_franchise_contracts_end_date',
                        'franchise_contracts', ['tenant_id', 'end_date'])

    # ─── 2. franchise_fee_records — 收费记录 ─────────────────────────────────
    if 'franchise_fee_records' not in existing:
        op.create_table(
            'franchise_fee_records',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text('gen_random_uuid()')),
            sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('franchisee_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('contract_id', postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column('fee_type', sa.VARCHAR(30), nullable=False,
                      comment='joining_fee/royalty/management_fee/marketing_fee/deposit'),
            sa.Column('period_start', sa.DATE(), nullable=True),
            sa.Column('period_end', sa.DATE(), nullable=True),
            sa.Column('amount_fen', sa.BIGINT(), nullable=False),
            sa.Column('paid_fen', sa.BIGINT(), nullable=False, server_default='0'),
            sa.Column('due_date', sa.DATE(), nullable=True),
            sa.Column('status', sa.VARCHAR(20), nullable=False, server_default='unpaid'),
            sa.Column('receipt_no', sa.VARCHAR(50), nullable=True),
            sa.Column('receipt_url', sa.Text(), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                      server_default=sa.text('NOW()'), nullable=False),
            sa.Column('updated_at', sa.TIMESTAMP(timezone=True),
                      server_default=sa.text('NOW()'), nullable=False),
            sa.ForeignKeyConstraint(
                ['contract_id'], ['franchise_contracts.id'],
                ondelete='SET NULL',
                name='fk_franchise_fee_records_contract_id',
            ),
        )
        op.create_index('idx_franchise_fee_records_tenant',
                        'franchise_fee_records', ['tenant_id'])
        op.create_index('idx_franchise_fee_records_franchisee',
                        'franchise_fee_records', ['tenant_id', 'franchisee_id'])
        op.create_index('idx_franchise_fee_records_due_date',
                        'franchise_fee_records', ['tenant_id', 'due_date'])

    # ─── RLS 策略（幂等） ────────────────────────────────────────────────────
    for table in ('franchise_contracts', 'franchise_fee_records'):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE tablename = '{table}'
                    AND policyname = '{table}_tenant_isolation'
                ) THEN
                    EXECUTE 'CREATE POLICY {table}_tenant_isolation ON {table}
                        USING (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::UUID)';
                END IF;
            END$$;
        """)


def downgrade() -> None:
    for table in ('franchise_contracts', 'franchise_fee_records'):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")

    op.drop_table('franchise_fee_records')
    op.drop_table('franchise_contracts')
