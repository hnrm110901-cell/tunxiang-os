"""活鲜批次追溯 — 批次入库/缸位管理/损耗日志

Revision: v214
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v214"
down_revision = "v213"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()


    # ── 活鲜批次表 ──

    if 'seafood_batches' not in existing:
        op.create_table(
            "seafood_batches",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("supplier_name", sa.VARCHAR(100), nullable=True),
            sa.Column("species", sa.VARCHAR(80), nullable=False, comment="品种：如波士顿龙虾"),
            sa.Column("batch_no", sa.VARCHAR(50), nullable=False),
            sa.Column("quantity", sa.INTEGER, nullable=False, comment="入库数量(尾/只)"),
            sa.Column("weight_g", sa.INTEGER, nullable=False, comment="入库总重(克)"),
            sa.Column("unit_price_fen", sa.BIGINT, nullable=False, comment="进货单价(分/斤)"),
            sa.Column("total_cost_fen", sa.BIGINT, nullable=False),
            sa.Column("received_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("status", sa.VARCHAR(20), server_default="active",
                      comment="active/depleted/expired"),
            sa.Column("remaining_qty", sa.INTEGER, nullable=False),
            sa.Column("remaining_weight_g", sa.INTEGER, nullable=False),
            sa.Column("origin", sa.VARCHAR(100), nullable=True, comment="产地"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.BOOLEAN, server_default="false", nullable=False),
        )
        op.create_index("ix_sb_tenant_store", "seafood_batches", ["tenant_id", "store_id"])
        op.create_index("ix_sb_species", "seafood_batches", ["tenant_id", "species"])
        _add_rls("seafood_batches", "sb")

        # ── 缸位表 ──

    if 'seafood_tanks' not in existing:
        op.create_table(
            "seafood_tanks",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tank_no", sa.VARCHAR(20), nullable=False, comment="缸号: A-01"),
            sa.Column("species", sa.VARCHAR(80), nullable=True),
            sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("current_qty", sa.INTEGER, server_default="0"),
            sa.Column("current_weight_g", sa.INTEGER, server_default="0"),
            sa.Column("temperature_c", sa.NUMERIC(4, 1), nullable=True),
            sa.Column("salinity_ppt", sa.NUMERIC(4, 1), nullable=True),
            sa.Column("survival_rate", sa.NUMERIC(5, 2), nullable=True, comment="存活率%"),
            sa.Column("status", sa.VARCHAR(20), server_default="active",
                      comment="active/empty/maintenance"),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.BOOLEAN, server_default="false", nullable=False),
        )
        op.create_index("ix_st_tenant_store", "seafood_tanks", ["tenant_id", "store_id"])
        _add_rls("seafood_tanks", "st")

        # ── 损耗日志 ──

    if 'seafood_mortality_logs' not in existing:
        op.create_table(
            "seafood_mortality_logs",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("tank_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("species", sa.VARCHAR(80), nullable=False),
            sa.Column("dead_qty", sa.INTEGER, nullable=False),
            sa.Column("dead_weight_g", sa.INTEGER, nullable=False),
            sa.Column("cause", sa.VARCHAR(50), nullable=True,
                      comment="natural/temperature/transport/unknown"),
            sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("notes", sa.TEXT, nullable=True),
            sa.Column("recorded_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.BOOLEAN, server_default="false", nullable=False),
        )
        op.create_index("ix_sml_tenant", "seafood_mortality_logs", ["tenant_id", "store_id"])
        _add_rls("seafood_mortality_logs", "sml")

    def _add_rls(table: str, prefix: str) -> None:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {prefix}_tenant ON {table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
        """)


def downgrade() -> None:
    for t, p in [("seafood_mortality_logs", "sml"), ("seafood_tanks", "st"), ("seafood_batches", "sb")]:
        op.execute(f"DROP POLICY IF EXISTS {p}_tenant ON {t}")
        op.drop_table(t)
