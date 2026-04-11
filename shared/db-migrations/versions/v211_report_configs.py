"""报表配置引擎表

变更：
  report_configs — 存储自定义/P0固定报表配置（含sql_template、default_params）

Revision: v211
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v211"
down_revision = "v210"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_configs",
        sa.Column("id", sa.VARCHAR(80), primary_key=True,
                  comment="报表唯一标识，P0报表用固定ID如 p0_biz_summary"),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.VARCHAR(120), nullable=False, comment="报表名称"),
        sa.Column("description", sa.TEXT, nullable=False, server_default="",
                  comment="报表描述"),
        sa.Column("category", sa.VARCHAR(40), nullable=False,
                  comment="分类: finance/operation/member/hr"),
        sa.Column("sql_template", sa.TEXT, nullable=False,
                  comment="参数化SQL模板，使用 :param 占位符"),
        sa.Column("default_params", postgresql.JSONB, nullable=False,
                  server_default="{}",
                  comment="默认查询参数"),
        sa.Column("dimensions", postgresql.JSONB, nullable=False,
                  server_default="[]",
                  comment="维度定义 [{name, label}]"),
        sa.Column("metrics", postgresql.JSONB, nullable=False,
                  server_default="[]",
                  comment="指标定义 [{name, label, unit, is_money_fen}]"),
        sa.Column("filters", postgresql.JSONB, nullable=False,
                  server_default="[]",
                  comment="筛选器定义 [{name, label, field_type, required, default}]"),
        sa.Column("is_system", sa.BOOLEAN, nullable=False, server_default="false",
                  comment="true=P0系统报表不可删除"),
        sa.Column("is_active", sa.BOOLEAN, nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("is_deleted", sa.BOOLEAN, server_default="false", nullable=False),
    )
    op.create_index("ix_rc_tenant", "report_configs", ["tenant_id"])
    op.create_index("ix_rc_category", "report_configs", ["tenant_id", "category"])

    # RLS
    op.execute("ALTER TABLE report_configs ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY report_configs_tenant ON report_configs "
        "USING (tenant_id = current_setting('app.tenant_id')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS report_configs_tenant ON report_configs")
    op.drop_index("ix_rc_category")
    op.drop_index("ix_rc_tenant")
    op.drop_table("report_configs")
