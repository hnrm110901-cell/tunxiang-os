"""Migrate existing delivery_orders data into orders table.

Revision ID: v398
Revises: v397
Create Date: 2026-05-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v398"
down_revision = "v397"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text("""
        INSERT INTO orders (
            tenant_id, store_id, order_type, sales_channel_id,
            total_fen, status, order_metadata, created_at, updated_at
        )
        SELECT
            d.tenant_id,
            d.store_id,
            'delivery' AS order_type,
            CASE d.platform
                WHEN 'meituan' THEN 'delivery_meituan'
                WHEN 'eleme' THEN 'delivery_eleme'
                WHEN 'douyin' THEN 'delivery_douyin'
                ELSE 'delivery_unknown'
            END AS sales_channel_id,
            d.total_fen,
            CASE d.status
                WHEN 1 THEN 'pending'
                WHEN 2 THEN 'confirmed'
                WHEN 3 THEN 'completed'
                WHEN 4 THEN 'cancelled'
                ELSE 'pending'
            END AS status,
            jsonb_build_object(
                'platform_order_id', d.platform_order_id,
                'platform', d.platform,
                'customer_phone', d.customer_phone,
                'delivery_address', d.delivery_address,
                'delivery_notes', d.notes,
                'migrated_from', 'delivery_orders',
                'original_id', d.id::text
            ) AS order_metadata,
            d.created_at,
            COALESCE(d.updated_at, d.created_at) AS updated_at
        FROM delivery_orders d
        WHERE NOT EXISTS (
            SELECT 1 FROM orders o
            WHERE o.tenant_id = d.tenant_id
              AND o.order_metadata->>'platform_order_id' = d.platform_order_id
        )
    """))


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        "DELETE FROM orders WHERE order_metadata->>'migrated_from' = 'delivery_orders'"
    ))
