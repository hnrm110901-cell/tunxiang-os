"""v078: 收货验收单 + 门店调拨单表

新增表：
1. receiving_orders       — 收货验收单
2. receiving_order_items  — 收货验收单明细
3. transfer_orders        — 门店调拨单
4. transfer_order_items   — 门店调拨单明细

RLS 策略：所有表通过 app.tenant_id 隔离

Revision ID: v078
Revises: v077
Create Date: 2026-03-31
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "v081"
down_revision= "v080"
branch_labels= None
depends_on= None


def upgrade() -> None:
    # ---------------------------------------------------------------
    # 1. receiving_orders
    # ---------------------------------------------------------------
    op.create_table(
        "receiving_orders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("procurement_order_id", UUID(as_uuid=True), nullable=True),
        sa.Column("supplier_id", UUID(as_uuid=True), nullable=True),
        sa.Column("delivery_note_no", sa.String(100), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("total_items", sa.Integer, nullable=False, server_default="0"),
        sa.Column("received_items", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rejected_items", sa.Integer, nullable=False, server_default="0"),
        sa.Column("receiver_id", UUID(as_uuid=True), nullable=True),
        sa.Column("inspected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remarks", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index("ix_receiving_orders_tenant_id", "receiving_orders", ["tenant_id"])
    op.create_index("ix_receiving_orders_store_id", "receiving_orders", ["store_id"])
    op.create_index("ix_receiving_orders_status", "receiving_orders", ["status"])
    op.create_index("ix_receiving_orders_supplier_id", "receiving_orders", ["supplier_id"])

    # RLS
    op.execute("ALTER TABLE receiving_orders ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY receiving_orders_tenant_isolation ON receiving_orders
            USING (tenant_id = current_setting('app.tenant_id')::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid)
    """)

    # ---------------------------------------------------------------
    # 2. receiving_order_items
    # ---------------------------------------------------------------
    op.create_table(
        "receiving_order_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("receiving_order_id", UUID(as_uuid=True), sa.ForeignKey("receiving_orders.id"), nullable=False),
        sa.Column("ingredient_id", UUID(as_uuid=True), sa.ForeignKey("ingredients.id"), nullable=False),
        sa.Column("ingredient_name", sa.String(100), nullable=False),
        sa.Column("expected_quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("expected_unit", sa.String(20), nullable=False),
        sa.Column("actual_quantity", sa.Numeric(12, 3), nullable=False, server_default="0"),
        sa.Column("accepted_quantity", sa.Numeric(12, 3), nullable=False, server_default="0"),
        sa.Column("rejected_quantity", sa.Numeric(12, 3), nullable=False, server_default="0"),
        sa.Column("unit_price_fen", sa.BigInteger, nullable=True),
        sa.Column("batch_no", sa.String(100), nullable=True),
        sa.Column("production_date", sa.Date, nullable=True),
        sa.Column("expiry_date", sa.Date, nullable=True),
        sa.Column("rejection_reason", sa.String(500), nullable=True),
        sa.Column("quality_photos", JSONB, nullable=True, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index("ix_receiving_order_items_tenant_id", "receiving_order_items", ["tenant_id"])
    op.create_index("ix_receiving_order_items_order_id", "receiving_order_items", ["receiving_order_id"])

    op.execute("ALTER TABLE receiving_order_items ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY receiving_order_items_tenant_isolation ON receiving_order_items
            USING (tenant_id = current_setting('app.tenant_id')::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid)
    """)

    # ---------------------------------------------------------------
    # 3. transfer_orders
    # ---------------------------------------------------------------
    op.create_table(
        "transfer_orders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("from_store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("to_store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("transfer_reason", sa.String(500), nullable=True),
        sa.Column("requested_by", UUID(as_uuid=True), nullable=True),
        sa.Column("approved_by", UUID(as_uuid=True), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index("ix_transfer_orders_tenant_id", "transfer_orders", ["tenant_id"])
    op.create_index("ix_transfer_orders_from_store_id", "transfer_orders", ["from_store_id"])
    op.create_index("ix_transfer_orders_to_store_id", "transfer_orders", ["to_store_id"])
    op.create_index("ix_transfer_orders_status", "transfer_orders", ["status"])

    op.execute("ALTER TABLE transfer_orders ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY transfer_orders_tenant_isolation ON transfer_orders
            USING (tenant_id = current_setting('app.tenant_id')::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid)
    """)

    # ---------------------------------------------------------------
    # 4. transfer_order_items
    # ---------------------------------------------------------------
    op.create_table(
        "transfer_order_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("transfer_order_id", UUID(as_uuid=True), sa.ForeignKey("transfer_orders.id"), nullable=False),
        sa.Column("ingredient_id", UUID(as_uuid=True), sa.ForeignKey("ingredients.id"), nullable=False),
        sa.Column("ingredient_name", sa.String(100), nullable=False),
        sa.Column("requested_quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("approved_quantity", sa.Numeric(12, 3), nullable=True),
        sa.Column("shipped_quantity", sa.Numeric(12, 3), nullable=True),
        sa.Column("received_quantity", sa.Numeric(12, 3), nullable=True),
        sa.Column("batch_no", sa.String(100), nullable=True),
        sa.Column("unit_cost_fen", sa.BigInteger, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index("ix_transfer_order_items_tenant_id", "transfer_order_items", ["tenant_id"])
    op.create_index("ix_transfer_order_items_order_id", "transfer_order_items", ["transfer_order_id"])

    op.execute("ALTER TABLE transfer_order_items ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY transfer_order_items_tenant_isolation ON transfer_order_items
            USING (tenant_id = current_setting('app.tenant_id')::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS transfer_order_items CASCADE")
    op.execute("DROP TABLE IF EXISTS transfer_orders CASCADE")
    op.execute("DROP TABLE IF EXISTS receiving_order_items CASCADE")
    op.execute("DROP TABLE IF EXISTS receiving_orders CASCADE")
