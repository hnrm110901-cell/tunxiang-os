"""v137 — 日清日结核心表 + RLS 策略（tx-ops E1-E8）

新增五张表：
  shift_handovers              — E1 班次交班记录
  daily_summaries              — E2 日营业汇总
  ops_issues                   — E5/E6 问题预警与整改
  inspection_reports           — E8 巡店质检报告
  employee_daily_performance   — E7 员工日绩效

每张表均含 tenant_id + RLS 策略（app.tenant_id），禁止 NULL 绕过。

Revision ID: v137
Revises: v136
Create Date: 2026-04-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "v137"
down_revision = "v136"
branch_labels = None
depends_on = None


def _add_rls(table_name: str) -> None:
    """为表启用 RLS 并创建策略 — 使用 app.tenant_id，禁止 NULL 绕过。"""
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table_name}")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table_name} "
        f"USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        f"WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def _drop_rls(table_name: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table_name}")
    op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # ── E1: shift_handovers ──────────────────────────────────────────────
    if "shift_handovers" not in _existing:
        op.create_table(
            "shift_handovers",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False, index=True),
            sa.Column("shift_date", sa.Date, nullable=False),
            sa.Column("shift_type", sa.String(20), nullable=False),
            sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("end_time", sa.DateTime(timezone=True)),
            sa.Column("handover_by", sa.String(100), nullable=False),
            sa.Column("received_by", sa.String(100)),
            sa.Column("cash_counted_fen", sa.Integer, server_default="0"),
            sa.Column("pos_cash_fen", sa.Integer, server_default="0"),
            sa.Column("cash_diff_fen", sa.Integer, server_default="0"),
            sa.Column("device_checklist", JSONB),
            sa.Column("notes", sa.Text),
            sa.Column("status", sa.String(20), server_default="pending"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("is_deleted", sa.Boolean, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='shift_handovers' AND column_name IN ('tenant_id', 'store_id', 'shift_date')) = 3 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_shift_handovers_store_date ON shift_handovers (tenant_id, store_id, shift_date)';
            END IF;
        END $$;
    """)
    _add_rls("shift_handovers")

    # ── E2: daily_summaries ──────────────────────────────────────────────
    if "daily_summaries" not in _existing:
        op.create_table(
            "daily_summaries",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False, index=True),
            sa.Column("summary_date", sa.Date, nullable=False),
            sa.Column("total_orders", sa.Integer, server_default="0"),
            sa.Column("dine_in_orders", sa.Integer, server_default="0"),
            sa.Column("takeaway_orders", sa.Integer, server_default="0"),
            sa.Column("banquet_orders", sa.Integer, server_default="0"),
            sa.Column("total_revenue_fen", sa.Integer, server_default="0"),
            sa.Column("actual_revenue_fen", sa.Integer, server_default="0"),
            sa.Column("total_discount_fen", sa.Integer, server_default="0"),
            sa.Column("avg_table_value_fen", sa.Integer, server_default="0"),
            sa.Column("max_discount_pct", sa.Float),
            sa.Column("abnormal_discounts", sa.Integer, server_default="0"),
            sa.Column("status", sa.String(20), server_default="draft"),
            sa.Column("confirmed_by", sa.String(100)),
            sa.Column("confirmed_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("is_deleted", sa.Boolean, server_default="false"),
            sa.UniqueConstraint("tenant_id", "store_id", "summary_date", name="uq_daily_summary_store_date"),
        )
    _add_rls("daily_summaries")

    # ── E5/E6: ops_issues ────────────────────────────────────────────────
    if "ops_issues" not in _existing:
        op.create_table(
            "ops_issues",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False, index=True),
            sa.Column("issue_date", sa.Date, nullable=False),
            sa.Column("issue_type", sa.String(30), nullable=False),
            sa.Column("severity", sa.String(20), server_default="medium"),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("description", sa.Text),
            sa.Column("evidence_urls", JSONB),
            sa.Column("assigned_to", sa.String(100)),
            sa.Column("due_at", sa.DateTime(timezone=True)),
            sa.Column("resolved_at", sa.DateTime(timezone=True)),
            sa.Column("resolution_notes", sa.Text),
            sa.Column("status", sa.String(20), server_default="open"),
            sa.Column("created_by", sa.String(100)),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("is_deleted", sa.Boolean, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='ops_issues' AND column_name IN ('tenant_id', 'store_id', 'issue_date')) = 3 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ops_issues_store_date ON ops_issues (tenant_id, store_id, issue_date)';
            END IF;
        END $$;
    """)
    _add_rls("ops_issues")

    # ── E8: inspection_reports ───────────────────────────────────────────
    if "inspection_reports" not in _existing:
        op.create_table(
            "inspection_reports",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False, index=True),
            sa.Column("inspection_date", sa.Date, nullable=False),
            sa.Column("inspector_id", sa.String(100), nullable=False),
            sa.Column("overall_score", sa.Float),
            sa.Column("dimensions", JSONB),
            sa.Column("photos", JSONB),
            sa.Column("action_items", JSONB),
            sa.Column("status", sa.String(20), server_default="draft"),
            sa.Column("acknowledged_by", sa.String(100)),
            sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
            sa.Column("notes", sa.Text),
            sa.Column("ack_notes", sa.Text),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("is_deleted", sa.Boolean, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='inspection_reports' AND column_name IN ('tenant_id', 'store_id', 'inspection_date')) = 3 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_inspection_reports_store_date ON inspection_reports (tenant_id, store_id, inspection_date)';
            END IF;
        END $$;
    """)
    _add_rls("inspection_reports")

    # ── E7: employee_daily_performance ───────────────────────────────────
    if "employee_daily_performance" not in _existing:
        op.create_table(
            "employee_daily_performance",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False, index=True),
            sa.Column("perf_date", sa.Date, nullable=False),
            sa.Column("employee_id", sa.String(100), nullable=False),
            sa.Column("employee_name", sa.String(100), server_default=""),
            sa.Column("role", sa.String(20), nullable=False),
            sa.Column("orders_handled", sa.Integer, server_default="0"),
            sa.Column("revenue_generated_fen", sa.Integer, server_default="0"),
            sa.Column("dishes_completed", sa.Integer, server_default="0"),
            sa.Column("tables_served", sa.Integer, server_default="0"),
            sa.Column("avg_service_score", sa.Float),
            sa.Column("base_commission_fen", sa.Integer, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("is_deleted", sa.Boolean, server_default="false"),
            sa.UniqueConstraint(
                "tenant_id",
                "store_id",
                "perf_date",
                "employee_id",
                name="uq_emp_perf_store_date_emp",
            ),
        )
    _add_rls("employee_daily_performance")


def downgrade() -> None:
    for table in [
        "employee_daily_performance",
        "inspection_reports",
        "ops_issues",
        "daily_summaries",
        "shift_handovers",
    ]:
        _drop_rls(table)
        op.drop_table(table)
