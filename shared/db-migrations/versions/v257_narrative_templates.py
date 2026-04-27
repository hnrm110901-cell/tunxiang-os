"""叙事模板表

变更：
  narrative_templates — 存储 AI 叙事报告模板配置（品牌焦点/提示词/指标权重/语气）

Revision: v257
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "v257"
down_revision = "v256"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()

    if "narrative_templates" not in existing:
        op.create_table(
            "narrative_templates",
            sa.Column("id", sa.VARCHAR(80), primary_key=True, comment="模板唯一标识"),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.VARCHAR(120), nullable=False, comment="模板名称"),
            sa.Column("brand_focus", sa.VARCHAR(200), nullable=True, comment="品牌关注焦点，如：营业额/毛利"),
            sa.Column("prompt_prefix", sa.TEXT, nullable=True, comment="AI 提示词前缀"),
            sa.Column(
                "metrics_weights",
                postgresql.JSONB,
                nullable=False,
                server_default="{}",
                comment="指标权重配置 {metric_key: weight}",
            ),
            sa.Column(
                "tone",
                sa.VARCHAR(40),
                nullable=False,
                server_default="professional",
                comment="语气风格: professional/executive/casual",
            ),
            sa.Column("is_default", sa.BOOLEAN, nullable=False, server_default="false", comment="是否为默认模板"),
            sa.Column("is_system", sa.BOOLEAN, nullable=False, server_default="false", comment="true=内置模板不可删除"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("is_deleted", sa.BOOLEAN, server_default="false", nullable=False),
        )
        op.create_index("ix_nt_tenant", "narrative_templates", ["tenant_id"])
        op.create_index("ix_nt_tenant_default", "narrative_templates", ["tenant_id", "is_default"])

    # RLS
    op.execute("ALTER TABLE narrative_templates ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'narrative_templates'
                AND policyname = 'narrative_templates_tenant'
            ) THEN
                EXECUTE 'CREATE POLICY narrative_templates_tenant ON narrative_templates '
                        'USING (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid)';
            END IF;
        END$$;
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS narrative_templates_tenant ON narrative_templates")
    op.drop_index("ix_nt_tenant_default")
    op.drop_index("ix_nt_tenant")
    op.drop_table("narrative_templates")
