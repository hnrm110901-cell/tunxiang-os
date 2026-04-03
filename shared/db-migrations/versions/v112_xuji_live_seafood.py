"""v112 — 徐记海鲜：活鲜菜品扩展字段 + 鱼缸管理

Revision ID: v112
Revises: v111
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "v112"
down_revision = "v111"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. dishes 表新增活鲜专属字段 ──────────────────────────────
    op.add_column("dishes", sa.Column(
        "pricing_method", sa.String(20), nullable=False,
        server_default="fixed",
        comment="计价方式：fixed=固定价 / weight=称重计价 / count=条头计价"
    ))
    op.add_column("dishes", sa.Column(
        "weight_unit", sa.String(10), nullable=True,
        comment="称重单位：jin=斤 / liang=两 / kg=千克 / g=克"
    ))
    op.add_column("dishes", sa.Column(
        "price_per_unit_fen", sa.Integer, nullable=True,
        comment="单位价格（分）—— 称重时=每斤价，计头时=每条/头价"
    ))
    op.add_column("dishes", sa.Column(
        "min_order_qty", sa.Numeric(6, 2), nullable=True,
        server_default="1.0",
        comment="最小点单量，如0.5斤起"
    ))
    op.add_column("dishes", sa.Column(
        "display_unit", sa.String(10), nullable=True,
        comment="展示单位，如：斤/条/头/位/份"
    ))
    op.add_column("dishes", sa.Column(
        "tank_zone_id", UUID(as_uuid=True), nullable=True,
        comment="所属鱼缸区域ID"
    ))
    op.add_column("dishes", sa.Column(
        "alive_rate_pct", sa.Integer, nullable=True,
        server_default="100",
        comment="历史成活率%（用于采购成本核算）"
    ))
    op.add_column("dishes", sa.Column(
        "live_stock_count", sa.Integer, nullable=True,
        server_default="0",
        comment="当前活鲜库存数量（条/头）"
    ))
    op.add_column("dishes", sa.Column(
        "live_stock_weight_g", sa.Integer, nullable=True,
        server_default="0",
        comment="当前活鲜库存重量（克）"
    ))

    # ── 2. fish_tank_zones 鱼缸区域表 ────────────────────────────
    op.create_table(
        "fish_tank_zones",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", UUID(as_uuid=True), nullable=False),
        sa.Column("zone_code", sa.String(20), nullable=False, comment="区域编码，如：A1/B2/海鲜池-1"),
        sa.Column("zone_name", sa.String(50), nullable=False, comment="展示名称，如：海鲜区A缸1号"),
        sa.Column("capacity_kg", sa.Numeric(8, 2), nullable=True, comment="容量（千克）"),
        sa.Column("water_temp_celsius", sa.Numeric(4, 1), nullable=True, comment="水温（℃）"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )

    # ── 3. live_seafood_weigh_records 活鲜称重记录表 ─────────────
    op.create_table(
        "live_seafood_weigh_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", UUID(as_uuid=True), nullable=True, comment="关联订单（称重确认前可为空）"),
        sa.Column("order_item_id", UUID(as_uuid=True), nullable=True),
        sa.Column("dish_id", UUID(as_uuid=True), nullable=False),
        sa.Column("dish_name", sa.String(100), nullable=False),
        sa.Column("tank_zone_id", UUID(as_uuid=True), nullable=True),
        # 称重数据
        sa.Column("weighed_qty", sa.Numeric(8, 3), nullable=False, comment="称重数量（按weight_unit）"),
        sa.Column("weight_unit", sa.String(10), nullable=False),
        sa.Column("price_per_unit_fen", sa.Integer, nullable=False, comment="称重时的单价（快照）"),
        sa.Column("amount_fen", sa.Integer, nullable=False, comment="金额 = weighed_qty * price_per_unit_fen"),
        # 操作信息
        sa.Column("weighed_by", UUID(as_uuid=True), nullable=True, comment="称重员工ID"),
        sa.Column("confirmed_by", UUID(as_uuid=True), nullable=True, comment="顾客/服务员确认人ID"),
        sa.Column("confirmed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending",
                  comment="pending=待确认 / confirmed=已确认 / cancelled=已取消"),
        sa.Column("print_ticket_id", sa.String(50), nullable=True, comment="打印流水号"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )

    # ── 4. 索引 ──────────────────────────────────────────────────
    op.create_index("ix_dishes_pricing_method", "dishes", ["pricing_method"])
    op.create_index("ix_dishes_tank_zone_id", "dishes", ["tank_zone_id"])
    op.create_index("ix_fish_tank_zones_store_id", "fish_tank_zones", ["store_id", "tenant_id"])
    op.create_index("ix_live_seafood_weigh_order_id", "live_seafood_weigh_records", ["order_id"])
    op.create_index("ix_live_seafood_weigh_status", "live_seafood_weigh_records", ["status", "store_id"])

    # ── 5. RLS 行级安全策略 ────────────────────────────────────────
    for table in ["fish_tank_zones", "live_seafood_weigh_records"]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
            USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
        """)

    # ── 6. updated_at 自动更新触发器 ──────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN NEW.updated_at = now(); RETURN NEW; END;
        $$ language 'plpgsql';
    """)
    for table in ["fish_tank_zones", "live_seafood_weigh_records"]:
        op.execute(f"""
            DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table};
            CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column();
        """)


def downgrade() -> None:
    # 删除表
    op.drop_table("live_seafood_weigh_records")
    op.drop_table("fish_tank_zones")
    # 删除 dishes 扩展字段
    for col in [
        "pricing_method", "weight_unit", "price_per_unit_fen",
        "min_order_qty", "display_unit", "tank_zone_id",
        "alive_rate_pct", "live_stock_count", "live_stock_weight_g"
    ]:
        op.drop_column("dishes", col)
