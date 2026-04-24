"""v154 — 活海鲜功能专用表

新增三张表：
  live_seafood_zones        — 鱼缸区域（替代旧 fish_tank_zones）
  live_seafood_stocks       — 活海鲜库存 / 菜品区域关联
  live_seafood_weigh_records — 称重记录（称重→确认→绑订单）

RLS 策略：NULLIF(current_setting('app.tenant_id', true), '')::uuid 模式。

Revision ID: v154
Revises: v153
Create Date: 2026-04-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "v154"
down_revision= "v153"
branch_labels= None
depends_on= None

_SAFE_CONDITION = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def _apply_rls(table: str) -> None:
    op.execute(f"""
        ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};
        CREATE POLICY {table}_tenant_isolation ON {table}
            AS PERMISSIVE FOR ALL
            USING ({_SAFE_CONDITION})
            WITH CHECK ({_SAFE_CONDITION});
    """)


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # ── 1. live_seafood_zones 鱼缸区域 ──────────────────────────────────────
    if "live_seafood_zones" not in _existing:
        op.create_table(
            "live_seafood_zones",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("zone_code", sa.String(20), nullable=False),
            sa.Column("zone_name", sa.String(100), nullable=False),
            sa.Column("capacity_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("capacity_weight_g", sa.Integer, nullable=False, server_default="0"),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
            sa.Column(
                "created_at", sa.TIMESTAMP(timezone=True),
                nullable=False, server_default=sa.text("now()"),
            ),
            sa.UniqueConstraint("tenant_id", "store_id", "zone_code",
                                name="uq_live_seafood_zones_tenant_store_code"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='live_seafood_zones' AND column_name IN ('tenant_id', 'store_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_live_seafood_zones_tenant_store ON live_seafood_zones (tenant_id, store_id)';
            END IF;
        END $$;
    """)
    _apply_rls("live_seafood_zones")

    # ── 2. live_seafood_stocks 活海鲜库存 / 菜品区域关联 ────────────────────
    if "live_seafood_stocks" not in _existing:
        op.create_table(
            "live_seafood_stocks",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("zone_id", UUID(as_uuid=True), nullable=True),
            sa.Column("zone_code", sa.String(20), nullable=True),
            sa.Column("dish_id", UUID(as_uuid=True), nullable=False),
            sa.Column("dish_name", sa.String(200), nullable=True),
            sa.Column("current_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("current_weight_g", sa.Integer, nullable=False, server_default="0"),
            sa.Column("price_per_unit_fen", sa.Integer, nullable=False, server_default="0"),
            sa.Column("display_unit", sa.String(20), nullable=False, server_default="'斤'"),
            sa.Column("pricing_method", sa.String(20), nullable=False, server_default="'weight'"),
            sa.Column("weight_unit", sa.String(20), nullable=True),
            sa.Column("alive_rate_pct", sa.Integer, nullable=False, server_default="95"),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
            sa.Column(
                "updated_at", sa.TIMESTAMP(timezone=True),
                nullable=False, server_default=sa.text("now()"),
            ),
            sa.Column(
                "created_at", sa.TIMESTAMP(timezone=True),
                nullable=False, server_default=sa.text("now()"),
            ),
            sa.ForeignKeyConstraint(
                ["zone_id"], ["live_seafood_zones.id"],
                name="fk_live_seafood_stocks_zone_id",
                ondelete="SET NULL",
            ),
            sa.UniqueConstraint("tenant_id", "store_id", "dish_id",
                                name="uq_live_seafood_stocks_tenant_store_dish"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='live_seafood_stocks' AND column_name IN ('tenant_id', 'store_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_live_seafood_stocks_tenant_store ON live_seafood_stocks (tenant_id, store_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='live_seafood_stocks' AND (column_name = 'zone_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_live_seafood_stocks_zone_id ON live_seafood_stocks (zone_id)';
            END IF;
        END $$;
    """)
    _apply_rls("live_seafood_stocks")

    # ── 3. live_seafood_weigh_records 称重记录 ──────────────────────────────
    if "live_seafood_weigh_records" not in _existing:
        op.create_table(
            "live_seafood_weigh_records",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("dish_id", UUID(as_uuid=True), nullable=False),
            sa.Column("dish_name", sa.String(200), nullable=True),
            sa.Column("zone_id", UUID(as_uuid=True), nullable=True),
            sa.Column("zone_code", sa.String(20), nullable=True),
            sa.Column("weighed_qty", sa.Numeric(8, 3), nullable=False),
            sa.Column("weight_unit", sa.String(20), nullable=False),
            sa.Column("price_per_unit_fen", sa.Integer, nullable=False),
            sa.Column("total_amount_fen", sa.Integer, nullable=False),
            sa.Column("order_id", UUID(as_uuid=True), nullable=True),
            sa.Column("confirmed_by", UUID(as_uuid=True), nullable=True),
            sa.Column("confirmed_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="'pending'"),
            sa.Column("weighed_by", UUID(as_uuid=True), nullable=True),
            sa.Column("notes", sa.Text, nullable=True),
            sa.Column(
                "created_at", sa.TIMESTAMP(timezone=True),
                nullable=False, server_default=sa.text("now()"),
            ),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='live_seafood_weigh_records' AND column_name IN ('tenant_id', 'store_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_live_seafood_weigh_records_tenant_store ON live_seafood_weigh_records (tenant_id, store_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='live_seafood_weigh_records' AND column_name IN ('tenant_id', 'store_id', 'status')) = 3 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_live_seafood_weigh_records_status ON live_seafood_weigh_records (tenant_id, store_id, status)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='live_seafood_weigh_records' AND (column_name = 'order_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_live_seafood_weigh_records_order_id ON live_seafood_weigh_records (order_id)';
            END IF;
        END $$;
    """)
    _apply_rls("live_seafood_weigh_records")


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS live_seafood_weigh_records_tenant_isolation "
        "ON live_seafood_weigh_records;"
    )
    op.drop_table("live_seafood_weigh_records")

    op.execute(
        "DROP POLICY IF EXISTS live_seafood_stocks_tenant_isolation "
        "ON live_seafood_stocks;"
    )
    op.drop_table("live_seafood_stocks")

    op.execute(
        "DROP POLICY IF EXISTS live_seafood_zones_tenant_isolation "
        "ON live_seafood_zones;"
    )
    op.drop_table("live_seafood_zones")
