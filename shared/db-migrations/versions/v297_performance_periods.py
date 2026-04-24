"""v256 — 绩效考核周期表

新增表：
  performance_periods  — 考核周期（月度/季度/年度）管理

含 RLS（NULLIF app.tenant_id）。

Revision ID: v256
Revises: v255
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "v297"
down_revision = "v255"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing_tables = sa.inspect(conn).get_table_names()

    # ── performance_periods ──────────────────────────────────────────────────
    if "performance_periods" not in existing_tables:
        op.create_table(
            "performance_periods",
            sa.Column("id", sa.UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", sa.UUID, nullable=False),
            sa.Column("name", sa.Text, nullable=False, comment="e.g. 2026年3月月度考核"),
            sa.Column(
                "period_type",
                sa.Text,
                nullable=False,
                server_default="monthly",
                comment="monthly / quarterly / annual",
            ),
            sa.Column("period_key", sa.Text, nullable=False, comment="YYYY-MM or YYYY-Q1 or YYYY"),
            sa.Column(
                "status",
                sa.Text,
                nullable=False,
                server_default="draft",
                comment="draft / in_progress / completed",
            ),
            sa.Column("participant_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("avg_score", sa.Numeric(5, 2), nullable=True),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        )
        op.create_index(
            "ix_pp_tenant_period_key",
            "performance_periods",
            ["tenant_id", "period_key"],
        )
        op.create_index(
            "ix_pp_tenant_status",
            "performance_periods",
            ["tenant_id", "status"],
        )
        op.execute("ALTER TABLE performance_periods ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE performance_periods FORCE ROW LEVEL SECURITY")
        op.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE tablename = 'performance_periods' AND policyname = 'perf_periods_tenant'
                ) THEN
                    EXECUTE $pol$
                        CREATE POLICY perf_periods_tenant ON performance_periods
                        USING (
                            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                        )
                    $pol$;
                END IF;
            END;
            $$
        """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS performance_periods CASCADE")
