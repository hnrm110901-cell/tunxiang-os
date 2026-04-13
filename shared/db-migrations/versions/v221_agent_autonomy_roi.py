"""Agent自治等级配置 + 自动执行日志 + ROI效果量化

Revision: v221
Down: v220
Tables:
  - agent_autonomy_configs    Agent自治等级配置（L1/L2/L3）
  - agent_auto_executions     Agent自动执行日志
  - agent_roi_metrics         Agent ROI效果量化指标
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v221"
down_revision = "v220"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()


    # ── Agent 自治等级配置 ──

    if 'agent_autonomy_configs' not in existing:
        op.create_table(
            "agent_autonomy_configs",
            sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("agent_id", sa.VARCHAR(100), nullable=False, comment="Agent标识"),
            sa.Column("level", sa.INTEGER, server_default="1", nullable=False, comment="自治等级: 1=仅建议, 2=半自动, 3=全自治"),
            sa.Column("auto_rules", postgresql.JSONB, server_default=sa.text("'[]'::jsonb"), comment="自动执行规则列表"),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.BOOLEAN, server_default=sa.text("false"), nullable=False),
        )
        op.create_index("ix_agent_autonomy_configs_tenant_agent", "agent_autonomy_configs", ["tenant_id", "agent_id"], unique=True)

        op.execute("""
            ALTER TABLE agent_autonomy_configs ENABLE ROW LEVEL SECURITY;
            CREATE POLICY agent_autonomy_configs_tenant ON agent_autonomy_configs
                USING (tenant_id = current_setting('app.tenant_id')::uuid);
        """)

        # ── Agent 自动执行日志 ──

    if 'agent_auto_executions' not in existing:
        op.create_table(
            "agent_auto_executions",
            sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("agent_id", sa.VARCHAR(100), nullable=False, comment="Agent标识"),
            sa.Column("action", sa.VARCHAR(200), nullable=False, comment="执行的操作"),
            sa.Column("params", postgresql.JSONB, server_default=sa.text("'{}'::jsonb"), comment="操作参数"),
            sa.Column("result", postgresql.JSONB, server_default=sa.text("'{}'::jsonb"), comment="执行结果"),
            sa.Column("status", sa.VARCHAR(20), server_default="executed", nullable=False, comment="状态: executed/pending/rejected/failed"),
            sa.Column("autonomy_level", sa.INTEGER, server_default="1", comment="执行时的自治等级"),
            sa.Column("executed_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.BOOLEAN, server_default=sa.text("false"), nullable=False),
        )
        op.create_index("ix_agent_auto_executions_tenant_agent", "agent_auto_executions", ["tenant_id", "agent_id"])
        op.create_index("ix_agent_auto_executions_status", "agent_auto_executions", ["tenant_id", "status"])
        op.create_index("ix_agent_auto_executions_executed_at", "agent_auto_executions", ["tenant_id", "executed_at"])

        op.execute("""
            ALTER TABLE agent_auto_executions ENABLE ROW LEVEL SECURITY;
            CREATE POLICY agent_auto_executions_tenant ON agent_auto_executions
                USING (tenant_id = current_setting('app.tenant_id')::uuid);
        """)

        # ── Agent ROI 效果量化指标 ──

    if 'agent_roi_metrics' not in existing:
        op.create_table(
            "agent_roi_metrics",
            sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("agent_id", sa.VARCHAR(100), nullable=False, comment="Agent标识"),
            sa.Column("metric_type", sa.VARCHAR(100), nullable=False, comment="指标类型"),
            sa.Column("value", sa.NUMERIC(18, 4), nullable=False, server_default="0", comment="指标值"),
            sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=True, comment="门店ID(可选,用于门店级汇总)"),
            sa.Column("period_start", sa.TIMESTAMP(timezone=True), nullable=False, comment="统计周期起始"),
            sa.Column("period_end", sa.TIMESTAMP(timezone=True), nullable=False, comment="统计周期结束"),
            sa.Column("metadata", postgresql.JSONB, server_default=sa.text("'{}'::jsonb"), comment="附加元数据"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.BOOLEAN, server_default=sa.text("false"), nullable=False),
        )
        op.create_index("ix_agent_roi_metrics_tenant_agent", "agent_roi_metrics", ["tenant_id", "agent_id"])
        op.create_index("ix_agent_roi_metrics_period", "agent_roi_metrics", ["tenant_id", "period_start", "period_end"])
        op.create_index("ix_agent_roi_metrics_type", "agent_roi_metrics", ["tenant_id", "agent_id", "metric_type"])

        op.execute("""
            ALTER TABLE agent_roi_metrics ENABLE ROW LEVEL SECURITY;
            CREATE POLICY agent_roi_metrics_tenant ON agent_roi_metrics
                USING (tenant_id = current_setting('app.tenant_id')::uuid);
        """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS agent_roi_metrics_tenant ON agent_roi_metrics;")
    op.drop_table("agent_roi_metrics")

    op.execute("DROP POLICY IF EXISTS agent_auto_executions_tenant ON agent_auto_executions;")
    op.drop_table("agent_auto_executions")

    op.execute("DROP POLICY IF EXISTS agent_autonomy_configs_tenant ON agent_autonomy_configs;")
    op.drop_table("agent_autonomy_configs")
