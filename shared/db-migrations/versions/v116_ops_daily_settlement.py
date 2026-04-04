"""v116 — 日清日结操作层核心表 (shift_handovers / daily_summaries /
daily_issues / inspection_reports / employee_daily_performance)

Revision ID: v116
Revises: v115
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "v116"
down_revision = "v115"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # ── shift_handovers 班次交班记录 (E1) ───────────────────────────────
    if "shift_handovers" not in _existing:
        op.create_table(
            "shift_handovers",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("shift_date", sa.Date, nullable=False),
            sa.Column("shift_type", sa.String(20), nullable=False,
                      comment="morning/afternoon/evening/night"),
            sa.Column("start_time", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("end_time", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("handover_by", UUID(as_uuid=True), nullable=True,
                      comment="交班人员UUID"),
            sa.Column("received_by", UUID(as_uuid=True), nullable=True,
                      comment="接班人员UUID"),
            sa.Column("cash_counted_fen", sa.Integer, nullable=False, server_default="0",
                      comment="清点现金（分）"),
            sa.Column("pos_cash_fen", sa.Integer, nullable=False, server_default="0",
                      comment="POS应收现金（分）"),
            sa.Column("cash_diff_fen", sa.Integer, nullable=False, server_default="0",
                      comment="差额=清点-POS（分）"),
            sa.Column("device_checklist", JSONB, nullable=True,
                      comment="设备检查清单 [{item, status, note}]"),
            sa.Column("notes", sa.Text, nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="'pending'",
                      comment="pending/confirmed/disputed"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
    else:
        # Table exists with older schema — add missing columns
        op.execute("ALTER TABLE shift_handovers ADD COLUMN IF NOT EXISTS shift_date DATE")
        op.execute("ALTER TABLE shift_handovers ADD COLUMN IF NOT EXISTS shift_type VARCHAR(20)")
        op.execute("ALTER TABLE shift_handovers ADD COLUMN IF NOT EXISTS handover_by UUID")
        op.execute("ALTER TABLE shift_handovers ADD COLUMN IF NOT EXISTS received_by UUID")
        op.execute("ALTER TABLE shift_handovers ADD COLUMN IF NOT EXISTS cash_counted_fen INTEGER DEFAULT 0")
        op.execute("ALTER TABLE shift_handovers ADD COLUMN IF NOT EXISTS pos_cash_fen INTEGER DEFAULT 0")
        op.execute("ALTER TABLE shift_handovers ADD COLUMN IF NOT EXISTS cash_diff_fen INTEGER DEFAULT 0")
        op.execute("ALTER TABLE shift_handovers ADD COLUMN IF NOT EXISTS device_checklist JSONB")
        op.execute("ALTER TABLE shift_handovers ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'pending'")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='shift_handovers' AND column_name='shift_date') THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_shift_handovers_tenant_store_date ON shift_handovers (tenant_id, store_id, shift_date)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='shift_handovers' AND (column_name = 'status')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_shift_handovers_status ON shift_handovers (status)';
            END IF;
        END $$;
    """)

    op.execute("ALTER TABLE shift_handovers ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS shift_handovers_tenant_isolation ON shift_handovers;")
    op.execute("""
        CREATE POLICY shift_handovers_tenant_isolation ON shift_handovers
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── daily_summaries 日营业汇总 (E2) ─────────────────────────────────
    if "daily_summaries" not in _existing:
        op.create_table(
            "daily_summaries",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("summary_date", sa.Date, nullable=False),
            sa.Column("total_orders", sa.Integer, nullable=False, server_default="0"),
            sa.Column("dine_in_orders", sa.Integer, nullable=False, server_default="0"),
            sa.Column("takeaway_orders", sa.Integer, nullable=False, server_default="0"),
            sa.Column("banquet_orders", sa.Integer, nullable=False, server_default="0"),
            sa.Column("total_revenue_fen", sa.Integer, nullable=False, server_default="0",
                      comment="含折扣前总额（分）"),
            sa.Column("actual_revenue_fen", sa.Integer, nullable=False, server_default="0",
                      comment="实收金额（分）"),
            sa.Column("total_discount_fen", sa.Integer, nullable=False, server_default="0",
                      comment="折扣总额（分）"),
            sa.Column("avg_table_value_fen", sa.Integer, nullable=False, server_default="0",
                      comment="人均消费（分）"),
            sa.Column("max_discount_pct", sa.Numeric(5, 2), nullable=True,
                      comment="最高折扣率 0-100"),
            sa.Column("abnormal_discounts", sa.Integer, nullable=False, server_default="0",
                      comment="异常折扣数（折扣率>30%且未审批）"),
            sa.Column("status", sa.String(20), nullable=False, server_default="'draft'",
                      comment="draft/confirmed/locked"),
            sa.Column("confirmed_by", UUID(as_uuid=True), nullable=True),
            sa.Column("confirmed_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
            sa.UniqueConstraint("tenant_id", "store_id", "summary_date",
                                name="uq_daily_summary_store_date"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='daily_summaries' AND column_name IN ('tenant_id', 'store_id', 'summary_date')) = 3 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_daily_summaries_tenant_store_date ON daily_summaries (tenant_id, store_id, summary_date)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='daily_summaries' AND (column_name = 'status')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_daily_summaries_status ON daily_summaries (status)';
            END IF;
        END $$;
    """)

    op.execute("ALTER TABLE daily_summaries ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS daily_summaries_tenant_isolation ON daily_summaries;")
    op.execute("""
        CREATE POLICY daily_summaries_tenant_isolation ON daily_summaries
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── daily_issues 日问题记录 (E5/E6) ─────────────────────────────────
    if "daily_issues" not in _existing:
        op.create_table(
            "daily_issues",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("issue_date", sa.Date, nullable=False),
            sa.Column("issue_type", sa.String(30), nullable=False,
                      comment="discount_abuse/food_safety/device_fault/service/kds_timeout"),
            sa.Column("severity", sa.String(10), nullable=False, server_default="'medium'",
                      comment="critical/high/medium/low"),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("evidence_urls", JSONB, nullable=True,
                      comment="照片/视频URL列表"),
            sa.Column("assigned_to", UUID(as_uuid=True), nullable=True,
                      comment="指派处理人UUID"),
            sa.Column("due_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("resolution_notes", sa.Text, nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="'open'",
                      comment="open/in_progress/resolved/closed/escalated"),
            sa.Column("created_by", UUID(as_uuid=True), nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='daily_issues' AND column_name IN ('tenant_id', 'store_id', 'issue_date')) = 3 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_daily_issues_tenant_store_date ON daily_issues (tenant_id, store_id, issue_date)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='daily_issues' AND column_name IN ('status', 'severity')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_daily_issues_status_severity ON daily_issues (status, severity)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='daily_issues' AND (column_name = 'assigned_to')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_daily_issues_assigned_to ON daily_issues (assigned_to)';
            END IF;
        END $$;
    """)

    op.execute("ALTER TABLE daily_issues ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS daily_issues_tenant_isolation ON daily_issues;")
    op.execute("""
        CREATE POLICY daily_issues_tenant_isolation ON daily_issues
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── inspection_reports 巡店质检报告 (E8) ────────────────────────────
    if "inspection_reports" not in _existing:
        op.create_table(
            "inspection_reports",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("inspection_date", sa.Date, nullable=False),
            sa.Column("inspector_id", UUID(as_uuid=True), nullable=False,
                      comment="巡店人（总部/区域经理）UUID"),
            sa.Column("overall_score", sa.Numeric(4, 1), nullable=True,
                      comment="综合评分 0-100"),
            sa.Column("dimensions", JSONB, nullable=True,
                      comment="[{name, score, max_score, issues:[]}]"),
            sa.Column("photos", JSONB, nullable=True,
                      comment="[{url, caption, issue_id?}]"),
            sa.Column("action_items", JSONB, nullable=True,
                      comment="[{item, deadline, owner}]"),
            sa.Column("status", sa.String(20), nullable=False, server_default="'draft'",
                      comment="draft/submitted/acknowledged/closed"),
            sa.Column("acknowledged_by", UUID(as_uuid=True), nullable=True),
            sa.Column("acknowledged_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='inspection_reports' AND column_name IN ('tenant_id', 'store_id', 'inspection_date')) = 3 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_inspection_reports_tenant_store_date ON inspection_reports (tenant_id, store_id, inspection_date)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='inspection_reports' AND (column_name = 'inspector_id')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_inspection_reports_inspector ON inspection_reports (inspector_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='inspection_reports' AND (column_name = 'status')) = 1 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_inspection_reports_status ON inspection_reports (status)';
            END IF;
        END $$;
    """)

    op.execute("ALTER TABLE inspection_reports ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS inspection_reports_tenant_isolation ON inspection_reports;")
    op.execute("""
        CREATE POLICY inspection_reports_tenant_isolation ON inspection_reports
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)

    # ── employee_daily_performance 员工日绩效 (E7) ───────────────────────
    if "employee_daily_performance" not in _existing:
        op.create_table(
            "employee_daily_performance",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("perf_date", sa.Date, nullable=False),
            sa.Column("employee_id", UUID(as_uuid=True), nullable=False),
            sa.Column("employee_name", sa.String(100), nullable=False, server_default="''"),
            sa.Column("role", sa.String(30), nullable=False,
                      comment="cashier/chef/waiter/runner"),
            sa.Column("orders_handled", sa.Integer, nullable=False, server_default="0"),
            sa.Column("revenue_generated_fen", sa.Integer, nullable=False, server_default="0",
                      comment="收银员经手订单总金额（分）"),
            sa.Column("dishes_completed", sa.Integer, nullable=False, server_default="0",
                      comment="厨师完成菜品数"),
            sa.Column("tables_served", sa.Integer, nullable=False, server_default="0",
                      comment="服务员服务桌数"),
            sa.Column("avg_service_score", sa.Numeric(3, 1), nullable=True,
                      comment="顾客评分均值"),
            sa.Column("base_commission_fen", sa.Integer, nullable=False, server_default="0",
                      comment="基础提成（分）"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.UniqueConstraint("tenant_id", "store_id", "perf_date", "employee_id",
                                name="uq_employee_daily_perf"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='employee_daily_performance' AND column_name IN ('tenant_id', 'store_id', 'perf_date')) = 3 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_employee_daily_perf_tenant_store_date ON employee_daily_performance (tenant_id, store_id, perf_date)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='employee_daily_performance' AND column_name IN ('employee_id', 'perf_date')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_employee_daily_perf_employee ON employee_daily_performance (employee_id, perf_date)';
            END IF;
        END $$;
    """)

    op.execute("ALTER TABLE employee_daily_performance ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS employee_daily_performance_tenant_isolation ON employee_daily_performance;")
    op.execute("""
        CREATE POLICY employee_daily_performance_tenant_isolation ON employee_daily_performance
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS employee_daily_performance_tenant_isolation ON employee_daily_performance;")
    op.drop_table("employee_daily_performance")

    op.execute("DROP POLICY IF EXISTS inspection_reports_tenant_isolation ON inspection_reports;")
    op.drop_table("inspection_reports")

    op.execute("DROP POLICY IF EXISTS daily_issues_tenant_isolation ON daily_issues;")
    op.drop_table("daily_issues")

    op.execute("DROP POLICY IF EXISTS daily_summaries_tenant_isolation ON daily_summaries;")
    op.drop_table("daily_summaries")

    op.execute("DROP POLICY IF EXISTS shift_handovers_tenant_isolation ON shift_handovers;")
    op.drop_table("shift_handovers")
