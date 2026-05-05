"""Rename delivery_orders to delivery_orders_deprecated.

Revision ID: v399
Revises: v398
Create Date: 2026-05-05
"""
from alembic import op
import sqlalchemy as sa

revision = "v399"
down_revision = "v398"
branch_labels = None
depends_on = None


def upgrade():
    op.rename_table("delivery_orders", "delivery_orders_deprecated")


def downgrade():
    op.rename_table("delivery_orders_deprecated", "delivery_orders")
