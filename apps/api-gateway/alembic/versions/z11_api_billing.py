"""z11 — API billing cycles & invoices

Revision ID: z11
Revises: z10
Create Date: 2026-03-07

Adds:
  api_billing_cycles  — monthly billing summary per developer
  api_invoices        — generated invoice records (printable)
"""
from alembic import op
import sqlalchemy as sa

revision = 'z11'
down_revision = 'z10'
branch_labels = None
depends_on = None

# Billing tier pricing (cents / 1000 calls)
# This is captured in the code; the table just stores actual amounts.


def upgrade() -> None:
    # ── api_billing_cycles ────────────────────────────────────────────────────
    op.create_table(
        'api_billing_cycles',
        sa.Column('id',               sa.String(36),  primary_key=True),
        sa.Column('developer_id',     sa.String(36),
                  sa.ForeignKey('isv_developers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('period',           sa.String(7),   nullable=False),   # 'YYYY-MM'
        sa.Column('total_calls',      sa.BigInteger,  nullable=False, server_default='0'),
        sa.Column('billable_calls',   sa.BigInteger,  nullable=False, server_default='0'),
        sa.Column('free_quota',       sa.BigInteger,  nullable=False, server_default='0'),
        sa.Column('overage_calls',    sa.BigInteger,  nullable=False, server_default='0'),
        sa.Column('amount_fen',       sa.BigInteger,  nullable=False, server_default='0'),  # 分
        sa.Column('amount_yuan',      sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('status',           sa.String(20),  nullable=False, server_default='draft'),
        # draft → finalized → invoiced
        sa.Column('finalized_at',     sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at',       sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at',       sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('developer_id', 'period', name='uq_billing_dev_period'),
    )
    op.create_index('ix_abc_period',    'api_billing_cycles', ['period'])
    op.create_index('ix_abc_developer', 'api_billing_cycles', ['developer_id'])
    op.create_index('ix_abc_status',    'api_billing_cycles', ['status'])

    # ── api_invoices ──────────────────────────────────────────────────────────
    op.create_table(
        'api_invoices',
        sa.Column('id',           sa.String(36),  primary_key=True),
        sa.Column('cycle_id',     sa.String(36),
                  sa.ForeignKey('api_billing_cycles.id', ondelete='CASCADE'), nullable=False),
        sa.Column('developer_id', sa.String(36),  nullable=False),
        sa.Column('period',       sa.String(7),   nullable=False),
        sa.Column('invoice_no',   sa.String(30),  nullable=False, unique=True),
        # e.g. INV-2026-03-DEV001
        sa.Column('amount_yuan',  sa.Numeric(12, 2), nullable=False),
        sa.Column('line_items',   sa.Text,        nullable=True),     # JSON breakdown
        sa.Column('status',       sa.String(20),  nullable=False, server_default='unpaid'),
        # unpaid → paid → void
        sa.Column('issued_at',    sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('paid_at',      sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_ai_developer', 'api_invoices', ['developer_id'])
    op.create_index('ix_ai_period',    'api_invoices', ['period'])
    op.create_index('ix_ai_status',    'api_invoices', ['status'])


def downgrade() -> None:
    op.drop_table('api_invoices')
    op.drop_table('api_billing_cycles')
