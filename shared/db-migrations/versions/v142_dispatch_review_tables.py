"""v142 — 自动派单任务 + 周月复盘报告 + 问题追踪 + 知识案例库 + 区域整改

新增六张表：
  dispatch_tasks           — Agent预警→自动派单任务（D7模块）
  dispatch_rules           — 派单规则配置（按预警类型）
  review_reports           — 周度/月度复盘报告（D8模块）
  review_issues            — 门店运营问题（D8模块）
  knowledge_cases          — 经营案例/知识库（D8模块）
  regional_rectifications  — 区域整改任务（E8模块）

Revision ID: v142
Revises: v141
Create Date: 2026-04-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "v142"
down_revision = "v141"
branch_labels = None
depends_on = None

_SAFE_RLS = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
)


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # ── dispatch_rules 派单规则配置 ──────────────────────────────────────
    if "dispatch_rules" not in _existing:
        op.create_table(
        "dispatch_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("alert_type", sa.String(50), nullable=False),
        sa.Column("assignee_role", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="normal"),
        sa.Column("escalation_minutes", sa.Integer, nullable=False, server_default="30"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='dispatch_rules' AND column_name IN ('tenant_id', 'alert_type')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_dispatch_rules_tenant_type ON dispatch_rules (tenant_id, alert_type)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE dispatch_rules ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE dispatch_rules FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY dispatch_rules_rls ON dispatch_rules
        USING ({_SAFE_RLS})
        WITH CHECK ({_SAFE_RLS});
    """)

    # ── dispatch_tasks 自动派单任务 ──────────────────────────────────────
    if "dispatch_tasks" not in _existing:
        op.create_table(
            "dispatch_tasks",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("alert_type", sa.String(50), nullable=False),
            sa.Column("source_agent", sa.String(50), nullable=False, server_default="unknown"),
            sa.Column("summary", sa.String(500), nullable=False, server_default=""),
            sa.Column("detail", JSONB, nullable=True),
            sa.Column("severity", sa.String(20), nullable=False, server_default="normal"),
            sa.Column("assignee_roles", JSONB, nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("escalated_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("deadline_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='dispatch_tasks' AND column_name IN ('tenant_id', 'store_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_dispatch_tasks_tenant_store ON dispatch_tasks (tenant_id, store_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='dispatch_tasks' AND column_name IN ('tenant_id', 'status')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_dispatch_tasks_tenant_status ON dispatch_tasks (tenant_id, status)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='dispatch_tasks' AND column_name IN ('tenant_id', 'alert_type')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_dispatch_tasks_tenant_alert_type ON dispatch_tasks (tenant_id, alert_type)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='dispatch_tasks' AND (column_name = 'deadline_at')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_dispatch_tasks_deadline ON dispatch_tasks (deadline_at)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE dispatch_tasks ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE dispatch_tasks FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY dispatch_tasks_rls ON dispatch_tasks
        USING ({_SAFE_RLS})
        WITH CHECK ({_SAFE_RLS});
    """)

    # ── review_reports 周月复盘报告 ──────────────────────────────────────
    if "review_reports" not in _existing:
        op.create_table(
            "review_reports",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=True),
            sa.Column("region_id", sa.String(50), nullable=True),
            sa.Column("report_type", sa.String(20), nullable=False),
            sa.Column("period_start", sa.Date, nullable=False),
            sa.Column("period_end", sa.Date, nullable=False),
            sa.Column("period_label", sa.String(20), nullable=False, server_default=""),
            sa.Column("revenue_fen", sa.BigInteger, nullable=False, server_default="0"),
            sa.Column("order_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("avg_order_value_fen", sa.Integer, nullable=False, server_default="0"),
            sa.Column("gross_profit_rate", sa.Float, nullable=True),
            sa.Column("highlights", JSONB, nullable=True),
            sa.Column("issues", JSONB, nullable=True),
            sa.Column("recommendations", JSONB, nullable=True),
            sa.Column("raw_data", JSONB, nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='review_reports' AND column_name IN ('tenant_id', 'store_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_review_reports_tenant_store ON review_reports (tenant_id, store_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='review_reports' AND column_name IN ('tenant_id', 'report_type', 'period_start')) = 3 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_review_reports_tenant_type_period ON review_reports (tenant_id, report_type, period_start)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE review_reports ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE review_reports FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY review_reports_rls ON review_reports
        USING ({_SAFE_RLS})
        WITH CHECK ({_SAFE_RLS});
    """)

    # ── review_issues 门店运营问题 ────────────────────────────────────────
    if "review_issues" not in _existing:
        op.create_table(
            "review_issues",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("issue_type", sa.String(50), nullable=False),
            sa.Column("description", sa.Text, nullable=False),
            sa.Column("reporter_id", sa.String(100), nullable=False),
            sa.Column("assignee_id", sa.String(100), nullable=True),
            sa.Column("priority", sa.String(10), nullable=False, server_default="medium"),
            sa.Column("status", sa.String(20), nullable=False, server_default="open"),
            sa.Column("deadline", sa.Date, nullable=True),
            sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("notes", sa.Text, nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='review_issues' AND column_name IN ('tenant_id', 'store_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_review_issues_tenant_store ON review_issues (tenant_id, store_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='review_issues' AND column_name IN ('tenant_id', 'status')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_review_issues_tenant_status ON review_issues (tenant_id, status)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE review_issues ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE review_issues FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY review_issues_rls ON review_issues
        USING ({_SAFE_RLS})
        WITH CHECK ({_SAFE_RLS});
    """)

    # ── knowledge_cases 经营案例/知识库 ─────────────────────────────────
    if "knowledge_cases" not in _existing:
        op.create_table(
            "knowledge_cases",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=True),
            sa.Column("category", sa.String(50), nullable=False, server_default="operations"),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("description", sa.Text, nullable=False, server_default=""),
            sa.Column("problem", sa.Text, nullable=True),
            sa.Column("solution", sa.Text, nullable=True),
            sa.Column("outcome", sa.Text, nullable=True),
            sa.Column("keywords", JSONB, nullable=True),
            sa.Column("case_data", JSONB, nullable=True),
            sa.Column("view_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("is_featured", sa.Boolean, nullable=False, server_default="false"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='knowledge_cases' AND column_name IN ('tenant_id', 'category')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_knowledge_cases_tenant_category ON knowledge_cases (tenant_id, category)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='knowledge_cases' AND column_name IN ('tenant_id', 'store_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_knowledge_cases_tenant_store ON knowledge_cases (tenant_id, store_id)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE knowledge_cases ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE knowledge_cases FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY knowledge_cases_rls ON knowledge_cases
        USING ({_SAFE_RLS})
        WITH CHECK ({_SAFE_RLS});
    """)


    # ── regional_rectifications 区域整改任务 ─────────────────────────────
    if "regional_rectifications" not in _existing:
        op.create_table(
            "regional_rectifications",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("region_id", sa.String(50), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("issue_id", sa.String(100), nullable=False),
            sa.Column("assignee_id", sa.String(100), nullable=False),
            sa.Column("deadline", sa.Date, nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="dispatched"),
            sa.Column("progress_notes", JSONB, nullable=True),
            sa.Column("reviewer_id", sa.String(100), nullable=True),
            sa.Column("review_result", sa.String(10), nullable=True),
            sa.Column("review_comment", sa.Text, nullable=True),
            sa.Column("reviewed_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='regional_rectifications' AND column_name IN ('tenant_id', 'region_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_regional_rectifications_tenant_region ON regional_rectifications (tenant_id, region_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='regional_rectifications' AND column_name IN ('tenant_id', 'status')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_regional_rectifications_tenant_status ON regional_rectifications (tenant_id, status)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE regional_rectifications ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE regional_rectifications FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY regional_rectifications_rls ON regional_rectifications
        USING ({_SAFE_RLS})
        WITH CHECK ({_SAFE_RLS});
    """)


def downgrade() -> None:
    for table in [
        "regional_rectifications",
        "knowledge_cases",
        "review_issues",
        "review_reports",
        "dispatch_tasks",
        "dispatch_rules",
    ]:
        op.execute(f"DROP POLICY IF EXISTS {table}_rls ON {table};")
        op.drop_table(table)
