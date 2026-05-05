"""Add platform_raw_response to channel_canonical_orders.

Revision ID: v400
Revises: v399
Create Date: 2026-05-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v400"
down_revision = "v399"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "channel_canonical_orders",
        sa.Column("platform_raw_response", postgresql.JSONB, nullable=True),
    )


def downgrade():
    op.drop_column("channel_canonical_orders", "platform_raw_response")
