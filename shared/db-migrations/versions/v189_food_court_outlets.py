"""智慧商街档口管理 — 美食广场多档口并行收银

Revision ID: v189
Revises: v188
Create Date: 2026-04-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "v189"
down_revision = "v188"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── 1. outlets — 档口档案 ────────────────────────────────────────────────
    op.create_table(
        "outlets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False, comment="所属美食广场门店"),
        sa.Column("name", sa.VARCHAR(100), nullable=False, comment='档口名称，如"张记烤鱼"'),
        sa.Column("outlet_code", sa.VARCHAR(20), nullable=True, comment="档口编号，如A01/B02"),
        sa.Column("location", sa.VARCHAR(100), nullable=True, comment='区位描述，如"A区1号"'),
        sa.Column("owner_name", sa.VARCHAR(50), nullable=True, comment="档口负责人姓名"),
        sa.Column("owner_phone", sa.VARCHAR(20), nullable=True, comment="档口负责人电话"),
        sa.Column(
            "status", sa.VARCHAR(20), nullable=False, server_default="active", comment="active/inactive/suspended"
        ),
        sa.Column(
            "settlement_ratio",
            sa.NUMERIC(5, 4),
            nullable=False,
            server_default="1.0000",
            comment="结算分成比例，用于统一收银场景",
        ),
        sa.Column("is_deleted", sa.BOOLEAN(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_index("idx_outlets_tenant_id", "outlets", ["tenant_id"])
    op.create_index("idx_outlets_store_id", "outlets", ["tenant_id", "store_id"])

    # ─── 2. outlet_orders — 档口订单关联 ──────────────────────────────────────
    op.create_table(
        "outlet_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("outlet_id", postgresql.UUID(as_uuid=True), nullable=False, comment="关联档口"),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False, comment="关联主订单"),
        sa.Column("subtotal_fen", sa.BIGINT(), nullable=False, server_default="0", comment="该档口小计，单位：分"),
        sa.Column("item_count", sa.Integer(), nullable=True, server_default="0", comment="该档口品项数量"),
        sa.Column(
            "status",
            sa.VARCHAR(20),
            nullable=False,
            server_default="pending",
            comment="pending/confirmed/completed/cancelled",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["outlet_id"], ["outlets.id"], ondelete="RESTRICT"),
    )
    op.create_index("idx_outlet_orders_tenant_id", "outlet_orders", ["tenant_id"])
    op.create_index("idx_outlet_orders_outlet_id", "outlet_orders", ["outlet_id"])
    op.create_index("idx_outlet_orders_order_id", "outlet_orders", ["order_id"])

    # ─── RLS 策略（2张表） ────────────────────────────────────────────────────
    for table in ("outlets", "outlet_orders"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
            USING (tenant_id = (current_setting('app.tenant_id', true)::UUID))
        """)


def downgrade() -> None:
    for table in ("outlets", "outlet_orders"):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")

    op.drop_table("outlet_orders")
    op.drop_table("outlets")
