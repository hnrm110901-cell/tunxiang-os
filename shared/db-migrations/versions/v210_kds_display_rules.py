"""KDS 显示规则配置表

变更：
  kds_display_rules — 门店级 KDS 颜色/超时/渠道高亮规则

Revision: v210
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v210"
down_revision = "v209"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kds_display_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rules", postgresql.JSONB, nullable=False, server_default="{}",
                  comment="KDS 显示规则: timeout/colors/channel_colors 等"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("is_deleted", sa.BOOLEAN, server_default="false", nullable=False),
    )
    op.create_index("ix_kds_dr_tenant", "kds_display_rules", ["tenant_id"])
    op.create_index("ix_kds_dr_store", "kds_display_rules", ["store_id"])
    op.create_index(
        "uq_kds_dr_tenant_store",
        "kds_display_rules",
        ["tenant_id", "store_id"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )

    # RLS
    op.execute("ALTER TABLE kds_display_rules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kds_display_rules FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY kds_display_rules_tenant
        ON kds_display_rules
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS kds_display_rules_tenant ON kds_display_rules")
    op.drop_table("kds_display_rules")
