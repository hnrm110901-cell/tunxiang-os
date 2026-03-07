"""z10 — Webhook subscription & delivery logs

Revision ID: z10
Revises: z09
Create Date: 2026-03-07
"""
from alembic import op
import sqlalchemy as sa

revision = 'z10'
down_revision = 'z09'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── webhook_subscriptions ─────────────────────────────────────────────────
    op.create_table(
        'webhook_subscriptions',
        sa.Column('id',            sa.String(36),  primary_key=True),
        sa.Column('developer_id',  sa.String(36),  sa.ForeignKey('isv_developers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('endpoint_url',  sa.Text,        nullable=False),
        sa.Column('secret_hash',   sa.String(128), nullable=False),      # HMAC-SHA256 secret (hashed)
        sa.Column('events',        sa.Text,        nullable=False),      # JSON list of subscribed event types
        sa.Column('status',        sa.String(20),  nullable=False, server_default='active'),
        sa.Column('description',   sa.String(200), nullable=True),
        sa.Column('failure_count', sa.Integer,     nullable=False, server_default='0'),
        sa.Column('last_triggered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at',    sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at',    sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_ws_developer',   'webhook_subscriptions', ['developer_id'])
    op.create_index('ix_ws_status',      'webhook_subscriptions', ['status'])

    # ── webhook_delivery_logs ─────────────────────────────────────────────────
    op.create_table(
        'webhook_delivery_logs',
        sa.Column('id',              sa.String(36),  primary_key=True),
        sa.Column('subscription_id', sa.String(36),  sa.ForeignKey('webhook_subscriptions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_type',      sa.String(60),  nullable=False),
        sa.Column('payload_size',    sa.Integer,     nullable=True),         # bytes
        sa.Column('status',          sa.String(20),  nullable=False, server_default='pending'),
        sa.Column('http_status',     sa.Integer,     nullable=True),
        sa.Column('attempts',        sa.Integer,     nullable=False, server_default='0'),
        sa.Column('next_retry_at',   sa.DateTime(timezone=True), nullable=True),
        sa.Column('delivered_at',    sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message',   sa.Text,        nullable=True),
        sa.Column('created_at',      sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_wdl_subscription', 'webhook_delivery_logs', ['subscription_id'])
    op.create_index('ix_wdl_event_type',   'webhook_delivery_logs', ['event_type'])
    op.create_index('ix_wdl_status',       'webhook_delivery_logs', ['status'])
    # Partial index: pending/failed deliveries need retry polling
    op.execute(
        "CREATE INDEX ix_wdl_pending ON webhook_delivery_logs (next_retry_at) "
        "WHERE status IN ('pending', 'failed')"
    )


def downgrade() -> None:
    op.drop_table('webhook_delivery_logs')
    op.drop_table('webhook_subscriptions')
