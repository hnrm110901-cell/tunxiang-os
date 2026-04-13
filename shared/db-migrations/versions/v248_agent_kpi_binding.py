"""agent_kpi_binding — Agent KPI配置表 + 每日快照表（模块4.4 AI Agent KPI绑定）

若表已存在则跳过（幂等）。

Revision ID: v248
Revises: v247
Create Date: 2026-04-13
"""

from alembic import op
import sqlalchemy as sa

revision = "v248"
down_revision = "v247"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    # ── 1. agent_kpi_configs ────────────────────────────────────────────────
    if "agent_kpi_configs" not in existing_tables:
        op.create_table(
            "agent_kpi_configs",
            sa.Column(
                "id", sa.UUID(), nullable=False, primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", sa.UUID(), nullable=False, comment="租户ID（RLS）"),
            sa.Column("agent_id", sa.String(64), nullable=False, comment="Agent标识符"),
            sa.Column("kpi_type", sa.String(64), nullable=False, comment="KPI类型标识"),
            sa.Column("target_value", sa.Numeric(10, 4), nullable=False, comment="目标值"),
            sa.Column("unit", sa.String(32), nullable=False, server_default="", comment="单位（%/s/次/分等）"),
            sa.Column("alert_threshold", sa.Numeric(10, 4), nullable=True, comment="预警阈值（低于此值触发告警）"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true", comment="是否启用"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
            sa.Column(
                "updated_at", sa.TIMESTAMP(timezone=True),
                server_default=sa.text("NOW()"), onupdate=sa.text("NOW()"), nullable=False,
            ),
            comment="Agent KPI指标配置表（模块4.4）",
        )

        op.create_index("ix_agent_kpi_configs_tenant_id", "agent_kpi_configs", ["tenant_id"])
        op.create_index("ix_agent_kpi_configs_agent_id", "agent_kpi_configs", ["agent_id"])
        op.create_index(
            "ix_agent_kpi_configs_tenant_agent",
            "agent_kpi_configs",
            ["tenant_id", "agent_id", "kpi_type"],
        )

        conn.execute(sa.text("ALTER TABLE agent_kpi_configs ENABLE ROW LEVEL SECURITY"))
        conn.execute(sa.text("""
            CREATE POLICY agent_kpi_configs_tenant_isolation ON agent_kpi_configs
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
        """))

    # ── 2. agent_kpi_snapshots ──────────────────────────────────────────────
    if "agent_kpi_snapshots" not in existing_tables:
        op.create_table(
            "agent_kpi_snapshots",
            sa.Column(
                "id", sa.UUID(), nullable=False, primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", sa.UUID(), nullable=False, comment="租户ID（RLS）"),
            sa.Column("agent_id", sa.String(64), nullable=False, comment="Agent标识符"),
            sa.Column("kpi_type", sa.String(64), nullable=False, comment="KPI类型标识"),
            sa.Column("measured_value", sa.Numeric(10, 4), nullable=False, comment="实测值"),
            sa.Column("target_value", sa.Numeric(10, 4), nullable=False, comment="目标值（快照时的目标）"),
            sa.Column("achievement_rate", sa.Numeric(5, 4), nullable=False, comment="达成率（0-1）"),
            sa.Column("store_id", sa.UUID(), nullable=True, comment="门店ID（NULL表示跨门店汇总）"),
            sa.Column("snapshot_date", sa.Date(), nullable=False, comment="快照日期"),
            sa.Column("metadata", sa.JSON(), nullable=True, comment="附加数据（JSON）"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
            comment="Agent KPI每日快照表（模块4.4）",
        )

        op.create_index("ix_agent_kpi_snapshots_tenant_id", "agent_kpi_snapshots", ["tenant_id"])
        op.create_index("ix_agent_kpi_snapshots_agent_id", "agent_kpi_snapshots", ["agent_id"])
        op.create_index("ix_agent_kpi_snapshots_snapshot_date", "agent_kpi_snapshots", ["snapshot_date"])
        op.create_index(
            "ix_agent_kpi_snapshots_tenant_agent_date",
            "agent_kpi_snapshots",
            ["tenant_id", "agent_id", "snapshot_date"],
        )

        conn.execute(sa.text("ALTER TABLE agent_kpi_snapshots ENABLE ROW LEVEL SECURITY"))
        conn.execute(sa.text("""
            CREATE POLICY agent_kpi_snapshots_tenant_isolation ON agent_kpi_snapshots
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
        """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP POLICY IF EXISTS agent_kpi_snapshots_tenant_isolation ON agent_kpi_snapshots"))
    conn.execute(sa.text("DROP POLICY IF EXISTS agent_kpi_configs_tenant_isolation ON agent_kpi_configs"))
    op.drop_table("agent_kpi_snapshots")
    op.drop_table("agent_kpi_configs")
