"""Agent Registry 数据模型 — agent_templates / agent_versions / agent_deployments
Revision: v230
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v230"
down_revision = "v229"
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



    # --- agent_templates Agent模板表 ---

    if 'agent_templates' not in existing:
        op.create_table(
            "agent_templates",
            sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
            sa.Column("tenant_id", postgresql.UUID(), nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("display_name", sa.String(200)),
            sa.Column("description", sa.Text()),
            sa.Column("category", sa.String(50)),
            sa.Column("priority", sa.String(10), server_default=sa.text("'P2'")),
            sa.Column("run_location", sa.String(20), server_default=sa.text("'cloud'")),
            sa.Column("agent_level", sa.Integer(), server_default=sa.text("1")),
            sa.Column("config_json", postgresql.JSON()),
            sa.Column("model_preference", sa.String(100)),
            sa.Column("tool_whitelist", postgresql.JSON()),
            sa.Column("status", sa.String(20), server_default=sa.text("'draft'")),
            sa.Column("created_by", sa.String(100)),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
        )
        op.create_index("ix_at_tenant", "agent_templates", ["tenant_id"])
        op.create_index("ix_at_name", "agent_templates", ["name"])
        op.execute("""
            ALTER TABLE agent_templates
            ADD CONSTRAINT uq_agent_template_tenant_name UNIQUE (tenant_id, name)
        """)
        _add_rls("agent_templates", "at")

        # --- agent_versions Agent版本表 ---

    if 'agent_versions' not in existing:
        op.create_table(
            "agent_versions",
            sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
            sa.Column("tenant_id", postgresql.UUID(), nullable=False),
            sa.Column("template_id", postgresql.UUID(), nullable=False),
            sa.Column("version_tag", sa.String(50), nullable=False),
            sa.Column("skill_yaml_snapshot", postgresql.JSON()),
            sa.Column("prompt_snapshot", postgresql.JSON()),
            sa.Column("changelog", sa.Text()),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text("false")),
            sa.Column("published_at", sa.TIMESTAMP(timezone=True)),
            sa.Column("published_by", sa.String(100)),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
        )
        op.create_index("ix_av_tenant", "agent_versions", ["tenant_id"])
        op.create_index("ix_av_template", "agent_versions", ["template_id"])
        op.create_foreign_key(
            "fk_av_template", "agent_versions", "agent_templates",
            ["template_id"], ["id"],
        )
        op.execute("""
            ALTER TABLE agent_versions
            ADD CONSTRAINT uq_agent_version_template_tag UNIQUE (template_id, version_tag)
        """)
        _add_rls("agent_versions", "av")

        # --- agent_deployments Agent部署表 ---

    if 'agent_deployments' not in existing:
        op.create_table(
            "agent_deployments",
            sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
            sa.Column("tenant_id", postgresql.UUID(), nullable=False),
            sa.Column("template_id", postgresql.UUID(), nullable=False),
            sa.Column("version_id", postgresql.UUID(), nullable=False),
            sa.Column("scope_type", sa.String(20), nullable=False),
            sa.Column("scope_id", postgresql.UUID(), nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default=sa.text("true")),
            sa.Column("rollout_percent", sa.Integer(), server_default=sa.text("100")),
            sa.Column("allowed_actions", postgresql.JSON()),
            sa.Column("config_overrides", postgresql.JSON()),
            sa.Column("deployed_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("deployed_by", sa.String(100)),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
        )
        op.create_index("ix_ad_tenant", "agent_deployments", ["tenant_id"])
        op.create_index("ix_ad_template", "agent_deployments", ["template_id"])
        op.create_index("ix_agent_deployment_scope", "agent_deployments", ["scope_type", "scope_id"])
        op.create_foreign_key(
            "fk_ad_template", "agent_deployments", "agent_templates",
            ["template_id"], ["id"],
        )
        op.create_foreign_key(
            "fk_ad_version", "agent_deployments", "agent_versions",
            ["version_id"], ["id"],
        )
        _add_rls("agent_deployments", "ad")



def downgrade() -> None:
    op.drop_table("agent_deployments")
    op.drop_table("agent_versions")
    op.drop_table("agent_templates")
