"""v390 — Open API Platform: API key + webhook subscriptions

Phase 4 — Open API ecosystem for third-party developers.

Changes:
  1. Create `api_keys` table for third-party API key management
  2. Create `webhook_subscriptions` table for event-driven integrations
  3. Create `webhook_delivery_logs` table for delivery tracking
  4. Enable RLS on all new tables

Revision ID: v390_api_key_system
Revises: v389_vn_market
Create Date: 2026-05-03
"""
from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "v390_api_key_system"
down_revision: str = "v389_vn_market"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # 1. api_keys
    op.create_table(
        "api_keys",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.VARCHAR(100), nullable=False),
        sa.Column("key_prefix", sa.VARCHAR(10), nullable=False),
        sa.Column("key_hash", sa.VARCHAR(64), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=True, server_default=sa.text("'[]'::json")),
        sa.Column("rate_limit_rps", sa.Integer(), nullable=False, server_default=sa.text("10")),
        sa.Column("status", sa.VARCHAR(20), nullable=False, server_default=sa.text("'active'")),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("FALSE"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)

    # 2. webhook_subscriptions
    op.create_table(
        "webhook_subscriptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("api_key_id", sa.UUID(), nullable=True),
        sa.Column("url", sa.VARCHAR(2048), nullable=False),
        sa.Column("secret", sa.VARCHAR(64), nullable=True),
        sa.Column("events", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("status", sa.VARCHAR(20), nullable=False, server_default=sa.text("'active'")),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("timeout_ms", sa.Integer(), nullable=False, server_default=sa.text("5000")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("FALSE"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_webhook_subscriptions_tenant", "webhook_subscriptions", ["tenant_id"])
    op.create_index("ix_webhook_subscriptions_status", "webhook_subscriptions", ["status"])

    # 3. webhook_delivery_logs
    op.create_table(
        "webhook_delivery_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("subscription_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.VARCHAR(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("status", sa.VARCHAR(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("next_retry_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["webhook_subscriptions.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_webhook_delivery_status_next_retry",
        "webhook_delivery_logs",
        ["status", "next_retry_at"],
    )

    # 4. RLS
    op.execute("ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE webhook_subscriptions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE webhook_delivery_logs ENABLE ROW LEVEL SECURITY")

    op.execute(
        "CREATE POLICY api_keys_tenant_isolation ON api_keys "
        "USING (tenant_id = current_setting('app.tenant_id')::UUID)"
    )
    op.execute(
        "CREATE POLICY webhook_subscriptions_tenant_isolation ON webhook_subscriptions "
        "USING (tenant_id = current_setting('app.tenant_id')::UUID)"
    )
    op.execute(
        "CREATE POLICY webhook_delivery_logs_tenant_isolation ON webhook_delivery_logs "
        "USING (tenant_id = current_setting('app.tenant_id')::UUID)"
    )


def downgrade() -> None:
    op.drop_table("webhook_delivery_logs")
    op.drop_table("webhook_subscriptions")
    op.drop_table("api_keys")
