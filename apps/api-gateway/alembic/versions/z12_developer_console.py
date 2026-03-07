"""z12 — ISV developer console snapshots

Revision ID: z12
Revises: z11
Create Date: 2026-03-07

Adds:
  developer_console_snapshots — daily aggregate snapshot per developer
    (api calls, revenue, plugin health, settlement status in one row)
"""
from alembic import op
import sqlalchemy as sa

revision = 'z12'
down_revision = 'z11'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'developer_console_snapshots',
        sa.Column('id',               sa.String(36),  primary_key=True),
        sa.Column('developer_id',     sa.String(36),
                  sa.ForeignKey('isv_developers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('snapshot_date',    sa.Date,        nullable=False),
        # API usage
        sa.Column('api_calls_today',  sa.BigInteger,  nullable=False, server_default='0'),
        sa.Column('api_calls_month',  sa.BigInteger,  nullable=False, server_default='0'),
        sa.Column('api_quota_used_pct', sa.Numeric(5, 2), nullable=False, server_default='0'),
        # Plugin health
        sa.Column('published_plugins',  sa.Integer,   nullable=False, server_default='0'),
        sa.Column('total_installs',     sa.BigInteger,nullable=False, server_default='0'),
        sa.Column('avg_rating',         sa.Numeric(3, 2), nullable=True),
        sa.Column('new_installs_today', sa.Integer,   nullable=False, server_default='0'),
        # Revenue
        sa.Column('pending_settlement_yuan', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('last_paid_yuan',          sa.Numeric(12, 2), nullable=False, server_default='0'),
        # Webhook health
        sa.Column('webhook_count',           sa.Integer,         nullable=False, server_default='0'),
        sa.Column('webhook_failure_count',   sa.Integer,         nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('developer_id', 'snapshot_date', name='uq_dcs_dev_date'),
    )
    op.create_index('ix_dcs_developer',     'developer_console_snapshots', ['developer_id'])
    op.create_index('ix_dcs_snapshot_date', 'developer_console_snapshots', ['snapshot_date'])


def downgrade() -> None:
    op.drop_table('developer_console_snapshots')
