"""计件提成3.0 — 厨师/传菜员按品项按做法计件

变更：
  piecework_zones        — 计件区域（热菜区/凉菜区/传菜组等）
  piecework_schemes      — 计件方案（by_dish/by_method，绑定区域和岗位）
  piecework_scheme_items — 方案明细（品项或做法 × 单价）
  piecework_records      — 计件记录（员工每次计件流水，generated total_fee_fen）

Revision ID: v187
Revises: v186
Create Date: 2026-04-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v187"
down_revision = "v186b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 计件区域表 ─────────────────────────────────────────────────────────
    op.create_table(
        "piecework_zones",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=True,
                  comment="NULL=集团通用，非NULL=仅对该门店生效"),
        sa.Column("name", sa.VARCHAR(50), nullable=False,
                  comment="如：热菜区/凉菜区/传菜组"),
        sa.Column("description", sa.TEXT(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="TRUE"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_piecework_zones_tenant "
        "ON piecework_zones (tenant_id, store_id) "
        "WHERE is_active = TRUE"
    )

    # ── 计件方案表 ─────────────────────────────────────────────────────────
    op.create_table(
        "piecework_schemes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("zone_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.VARCHAR(100), nullable=False),
        sa.Column("calc_type", sa.VARCHAR(20), nullable=False,
                  comment="by_dish=按品项计件 / by_method=按做法计件"),
        sa.Column("applicable_role", sa.VARCHAR(50), nullable=False,
                  comment="chef=厨师 / waiter=服务员 / runner=传菜员"),
        sa.Column("effective_date", sa.Date(), nullable=True,
                  comment="生效日期，NULL=即时生效"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="TRUE"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["zone_id"], ["piecework_zones.id"],
                                name="fk_piecework_schemes_zone",
                                ondelete="SET NULL"),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_piecework_schemes_tenant "
        "ON piecework_schemes (tenant_id, applicable_role, is_active)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_piecework_schemes_zone "
        "ON piecework_schemes (zone_id) WHERE zone_id IS NOT NULL"
    )

    # ── 方案明细表 ─────────────────────────────────────────────────────────
    op.create_table(
        "piecework_scheme_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scheme_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dish_id", postgresql.UUID(as_uuid=True), nullable=True,
                  comment="calc_type=by_dish 时使用"),
        sa.Column("method_id", postgresql.UUID(as_uuid=True), nullable=True,
                  comment="calc_type=by_method 时使用"),
        sa.Column("dish_name", sa.VARCHAR(100), nullable=True,
                  comment="冗余存储品项/做法名称，避免跨服务join"),
        sa.Column("unit_fee_fen", sa.Integer(), nullable=False,
                  comment="每件提成金额，单位：分"),
        sa.Column("min_qty", sa.Integer(), nullable=False, server_default="1",
                  comment="最低起算件数"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["scheme_id"], ["piecework_schemes.id"],
                                name="fk_piecework_scheme_items_scheme",
                                ondelete="CASCADE"),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_piecework_scheme_items_scheme "
        "ON piecework_scheme_items (tenant_id, scheme_id)"
    )

    # ── 计件记录表 ─────────────────────────────────────────────────────────
    op.create_table(
        "piecework_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("zone_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scheme_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dish_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dish_name", sa.VARCHAR(100), nullable=True),
        sa.Column("method_name", sa.VARCHAR(50), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_fee_fen", sa.Integer(), nullable=False,
                  comment="计件时快照的单价，单位：分"),
        # GENERATED ALWAYS AS STORED 列：total_fee_fen = quantity * unit_fee_fen
        sa.Column("total_fee_fen", sa.Integer(),
                  sa.Computed("quantity * unit_fee_fen", persisted=True),
                  comment="合计提成金额，单位：分，由数据库自动计算"),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True,
                  comment="关联订单ID（来自tx-trade）"),
        sa.Column("recorded_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("NOW()")),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_piecework_records_employee "
        "ON piecework_records (tenant_id, employee_id, recorded_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_piecework_records_store_date "
        "ON piecework_records (tenant_id, store_id, recorded_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_piecework_records_dish "
        "ON piecework_records (tenant_id, dish_id, recorded_at DESC) "
        "WHERE dish_id IS NOT NULL"
    )

    # ── RLS 策略：piecework_zones ──────────────────────────────────────────
    op.execute("""
        ALTER TABLE piecework_zones ENABLE ROW LEVEL SECURITY;

        CREATE POLICY piecework_zones_tenant ON piecework_zones
            USING (tenant_id = current_setting('app.tenant_id')::uuid);
    """)

    # ── RLS 策略：piecework_schemes ───────────────────────────────────────
    op.execute("""
        ALTER TABLE piecework_schemes ENABLE ROW LEVEL SECURITY;

        CREATE POLICY piecework_schemes_tenant ON piecework_schemes
            USING (tenant_id = current_setting('app.tenant_id')::uuid);
    """)

    # ── RLS 策略：piecework_scheme_items ──────────────────────────────────
    op.execute("""
        ALTER TABLE piecework_scheme_items ENABLE ROW LEVEL SECURITY;

        CREATE POLICY piecework_scheme_items_tenant ON piecework_scheme_items
            USING (tenant_id = current_setting('app.tenant_id')::uuid);
    """)

    # ── RLS 策略：piecework_records ───────────────────────────────────────
    op.execute("""
        ALTER TABLE piecework_records ENABLE ROW LEVEL SECURITY;

        CREATE POLICY piecework_records_tenant ON piecework_records
            USING (tenant_id = current_setting('app.tenant_id')::uuid);
    """)


def downgrade() -> None:
    # 撤销 RLS
    op.execute("DROP POLICY IF EXISTS piecework_records_tenant ON piecework_records")
    op.execute("DROP POLICY IF EXISTS piecework_scheme_items_tenant ON piecework_scheme_items")
    op.execute("DROP POLICY IF EXISTS piecework_schemes_tenant ON piecework_schemes")
    op.execute("DROP POLICY IF EXISTS piecework_zones_tenant ON piecework_zones")

    # 撤销索引
    op.execute("DROP INDEX IF EXISTS idx_piecework_records_dish")
    op.execute("DROP INDEX IF EXISTS idx_piecework_records_store_date")
    op.execute("DROP INDEX IF EXISTS idx_piecework_records_employee")
    op.execute("DROP INDEX IF EXISTS idx_piecework_scheme_items_scheme")
    op.execute("DROP INDEX IF EXISTS idx_piecework_schemes_zone")
    op.execute("DROP INDEX IF EXISTS idx_piecework_schemes_tenant")
    op.execute("DROP INDEX IF EXISTS idx_piecework_zones_tenant")

    # 撤销表（按依赖倒序）
    op.drop_table("piecework_records")
    op.drop_table("piecework_scheme_items")
    op.drop_table("piecework_schemes")
    op.drop_table("piecework_zones")
