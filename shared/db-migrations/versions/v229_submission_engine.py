"""上报引擎 — civic_submissions + civic_compliance_scores
Revision: v229
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "v229"
down_revision = "v228"
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

    # --- civic_submissions 统一上报日志 ---

    if "civic_submissions" not in existing:
        op.create_table(
            "civic_submissions",
            sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
            sa.Column("store_id", postgresql.UUID(), nullable=False),
            sa.Column("city_code", sa.String(6), nullable=False),
            sa.Column("domain", sa.String(30), nullable=False),
            sa.Column("submission_type", sa.String(20), nullable=False),
            sa.Column("platform_name", sa.String(100), nullable=False),
            sa.Column("endpoint_url", sa.String(500)),
            sa.Column("request_payload", postgresql.JSONB()),
            sa.Column("payload_hash", sa.String(64)),
            sa.Column("status", sa.String(20), server_default=sa.text("'pending'")),
            sa.Column("retry_count", sa.Integer(), server_default=sa.text("0")),
            sa.Column("max_retries", sa.Integer(), server_default=sa.text("3")),
            sa.Column("response_code", sa.Integer()),
            sa.Column("response_body", postgresql.JSONB()),
            sa.Column("error_message", sa.Text()),
            sa.Column("submitted_at", sa.TIMESTAMP(timezone=True)),
            sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
            sa.Column("next_retry_at", sa.TIMESTAMP(timezone=True)),
            sa.Column("correlation_id", postgresql.UUID()),
            sa.Column("tenant_id", postgresql.UUID(), nullable=False),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
        )
        op.create_index("ix_cs_tenant_store", "civic_submissions", ["tenant_id", "store_id"])
        op.create_index("ix_cs_status", "civic_submissions", ["tenant_id", "status"])
        op.create_index("ix_cs_domain", "civic_submissions", ["tenant_id", "domain"])
        op.create_index("ix_cs_hash", "civic_submissions", ["tenant_id", "payload_hash"])
        op.execute("""
            CREATE INDEX ix_cs_retry ON civic_submissions (status, next_retry_at)
            WHERE status = 'retry'
        """)
        _add_rls("civic_submissions", "cs")

        # --- civic_compliance_scores 门店合规评分 ---

    if "civic_compliance_scores" not in existing:
        op.create_table(
            "civic_compliance_scores",
            sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
            sa.Column("store_id", postgresql.UUID(), nullable=False),
            sa.Column("scored_at", sa.Date(), nullable=False),
            sa.Column("dimension_scores", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("total_score", sa.Numeric(5, 2), nullable=False),
            sa.Column("risk_level", sa.String(10), nullable=False, server_default=sa.text("'green'")),
            sa.Column("top_issues", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
            sa.Column("score_breakdown", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")),
            sa.Column("previous_score", sa.Numeric(5, 2)),
            sa.Column("score_trend", sa.String(10)),
            sa.Column("tenant_id", postgresql.UUID(), nullable=False),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
        )
        op.create_index("ix_ccs_tenant_store", "civic_compliance_scores", ["tenant_id", "store_id"])
        op.create_index("ix_ccs_date", "civic_compliance_scores", ["tenant_id", "scored_at"])
        op.create_index("ix_ccs_risk", "civic_compliance_scores", ["tenant_id", "risk_level"])
        op.create_index(
            "ix_ccs_unique",
            "civic_compliance_scores",
            ["tenant_id", "store_id", "scored_at"],
            unique=True,
        )
        _add_rls("civic_compliance_scores", "ccs")


def downgrade() -> None:
    op.drop_table("civic_compliance_scores")
    op.drop_table("civic_submissions")
