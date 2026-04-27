"""城市监管基础 — civic_city_profiles + store_civic_registries
Revision: v225
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "v225"
down_revision = "v224"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()

    def _add_rls(table: str, prefix: str) -> None:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='{table}' AND policyname='{prefix}_tenant') THEN
                    EXECUTE 'CREATE POLICY {prefix}_tenant ON {table}
                        USING (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::UUID)
                        WITH CHECK (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::UUID)';
                END IF;
            END$$;
        """)

    # --- civic_city_profiles 城市监管档案 ---

    if "civic_city_profiles" not in existing:
        op.create_table(
            "civic_city_profiles",
            sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
            sa.Column("city_code", sa.String(6), nullable=False),
            sa.Column("city_name", sa.String(50)),
            sa.Column("province", sa.String(20)),
            sa.Column("enabled_domains", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
            sa.Column("adapter_class", sa.String(100)),
            sa.Column("platform_configs", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
            sa.Column("tenant_id", postgresql.UUID(), nullable=False),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
        )
        op.create_index("ix_ccp_tenant", "civic_city_profiles", ["tenant_id"])
        op.create_index("ix_ccp_tenant_city", "civic_city_profiles", ["tenant_id", "city_code"], unique=True)
        _add_rls("civic_city_profiles", "ccp")

        # --- store_civic_registries 门店监管注册 ---

    if "store_civic_registries" not in existing:
        op.create_table(
            "store_civic_registries",
            sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
            sa.Column("store_id", postgresql.UUID(), nullable=False),
            sa.Column("city_code", sa.String(6), nullable=False),
            sa.Column("regulatory_id", sa.String(100)),
            sa.Column("registration_status", sa.String(20), server_default=sa.text("'pending'")),
            sa.Column("activated_domains", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
            sa.Column("platform_credentials", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")),
            sa.Column("notes", sa.Text()),
            sa.Column("tenant_id", postgresql.UUID(), nullable=False),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
        )
        op.create_index("ix_scr_tenant_store", "store_civic_registries", ["tenant_id", "store_id"])
        op.create_index("ix_scr_city", "store_civic_registries", ["tenant_id", "city_code"])
        _add_rls("store_civic_registries", "scr")


def downgrade() -> None:
    op.drop_table("store_civic_registries")
    op.drop_table("civic_city_profiles")
