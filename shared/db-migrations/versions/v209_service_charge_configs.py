"""服务费配置表 + 服务费模板表

变更：
  service_charge_configs   — 门店级服务费配置（mode/参数/启用状态）
  service_charge_templates — 总部服务费模板（下发到门店）

Revision: v209
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v209"
down_revision = "v208"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()


    # ── 服务费模板表（总部级） ──

    if 'service_charge_templates' not in existing:
        op.create_table(
            "service_charge_templates",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.VARCHAR(100), nullable=False),
            sa.Column("rules", postgresql.JSONB, nullable=False, server_default="{}",
                      comment="收费规则: {mode, charge_per_person_fen, room_charge_fen, ...}"),
            sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="active",
                      comment="active/archived"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.Column("is_deleted", sa.BOOLEAN, server_default="false", nullable=False),
        )
        op.create_index("ix_sct_tenant", "service_charge_templates", ["tenant_id"])

        # RLS
        op.execute("ALTER TABLE service_charge_templates ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE service_charge_templates FORCE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY service_charge_templates_tenant
            ON service_charge_templates
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
        """)

        # ── 门店服务费配置表 ──

    if 'service_charge_configs' not in existing:
        op.create_table(
            "service_charge_configs",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("mode", sa.VARCHAR(20), nullable=False, server_default="by_person",
                      comment="by_person/by_table/by_time/by_amount"),
            sa.Column("config", postgresql.JSONB, nullable=False, server_default="{}",
                      comment="完整配置JSON"),
            sa.Column("enabled", sa.BOOLEAN, server_default="true", nullable=False),
            sa.Column("source_template_id", postgresql.UUID(as_uuid=True), nullable=True,
                      comment="来源模板ID（null=门店手动配置）"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.Column("is_deleted", sa.BOOLEAN, server_default="false", nullable=False),
        )
        op.create_index("ix_scc_tenant_store", "service_charge_configs",
                        ["tenant_id", "store_id"], unique=True)

        # RLS
        op.execute("ALTER TABLE service_charge_configs ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE service_charge_configs FORCE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY service_charge_configs_tenant
            ON service_charge_configs
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
        """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS service_charge_configs_tenant ON service_charge_configs")
    op.drop_table("service_charge_configs")
    op.execute("DROP POLICY IF EXISTS service_charge_templates_tenant ON service_charge_templates")
    op.drop_table("service_charge_templates")
