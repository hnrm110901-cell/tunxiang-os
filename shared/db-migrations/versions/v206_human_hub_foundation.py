"""Human Hub 基础表 — Sprint 1: 编制/带教/认证/就绪度/高峰保障/DRI工单/AI预警/教练

Revision ID: v206
Revises: v205
Create Date: 2026-04-10
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "v206b"
down_revision = "v206"
branch_labels = None
depends_on = None

# 所有表名（创建顺序）
TABLES = [
    "store_staffing_templates",
    "staffing_snapshots",
    "mentorship_relations",
    "onboarding_paths",
    "position_certifications",
    "store_readiness_scores",
    "peak_guard_records",
    "dri_work_orders",
    "ai_alerts",
    "coach_sessions",
]


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()

    # ─── 1. store_staffing_templates — 门店编制模板 ──────────────────────────

    if "store_staffing_templates" not in existing:
        op.create_table(
            "store_staffing_templates",
            sa.Column(
                "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
            ),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("store_type", sa.VARCHAR(50), nullable=False, comment="店型: flagship/standard/mini/kiosk"),
            sa.Column("position", sa.VARCHAR(50), nullable=False, comment="岗位: manager/chef/waiter/cashier/cleaner"),
            sa.Column("shift", sa.VARCHAR(30), nullable=False, comment="班次: morning/afternoon/evening/full_day"),
            sa.Column(
                "day_type", sa.VARCHAR(20), nullable=False, server_default="weekday", comment="weekday/weekend/holiday"
            ),
            sa.Column("min_count", sa.Integer(), nullable=False, server_default="1", comment="最低人数"),
            sa.Column("recommended_count", sa.Integer(), nullable=False, server_default="1", comment="建议人数"),
            sa.Column("peak_buffer", sa.Integer(), nullable=False, server_default="0", comment="峰值保护位"),
            sa.Column("min_skill_level", sa.Integer(), nullable=False, server_default="1", comment="最低技能等级 1-5"),
            sa.Column("notes", sa.TEXT(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
            sa.UniqueConstraint(
                "tenant_id", "store_type", "position", "shift", "day_type", name="uq_staffing_tpl_composite"
            ),
        )
        op.create_index("idx_staffing_tpl_tenant", "store_staffing_templates", ["tenant_id"])

        # ─── 2. staffing_snapshots — 编制快照(对标用) ────────────────────────────

    if "staffing_snapshots" not in existing:
        op.create_table(
            "staffing_snapshots",
            sa.Column(
                "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
            ),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False, comment="门店ID"),
            sa.Column("snapshot_date", sa.Date(), nullable=False, comment="快照日期"),
            sa.Column("position", sa.VARCHAR(50), nullable=False),
            sa.Column("shift", sa.VARCHAR(30), nullable=False),
            sa.Column("required_count", sa.Integer(), nullable=False, server_default="0", comment="编制人数"),
            sa.Column("actual_count", sa.Integer(), nullable=False, server_default="0", comment="实际在岗"),
            sa.Column("gap", sa.Integer(), nullable=False, server_default="0", comment="缺口(负数=缺编)"),
            sa.Column(
                "skill_gap_detail", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", comment="技能缺口明细"
            ),
            sa.Column("impact_score", sa.Numeric(3, 1), server_default="0", comment="对营业影响评分 0-10"),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        )
        op.create_index("idx_staffing_snap_tenant", "staffing_snapshots", ["tenant_id"])
        op.create_index(
            "idx_staffing_snap_store_date",
            "staffing_snapshots",
            ["tenant_id", "store_id", sa.text("snapshot_date DESC")],
        )
        op.create_index(
            "idx_staffing_snap_gap",
            "staffing_snapshots",
            ["tenant_id", "snapshot_date", "gap"],
            postgresql_where=sa.text("gap < 0"),
        )

        # ─── 3. mentorship_relations — 带教关系 ──────────────────────────────────

    if "mentorship_relations" not in existing:
        op.create_table(
            "mentorship_relations",
            sa.Column(
                "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
            ),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("mentor_id", postgresql.UUID(as_uuid=True), nullable=False, comment="师傅员工ID"),
            sa.Column("mentee_id", postgresql.UUID(as_uuid=True), nullable=False, comment="学员员工ID"),
            sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("end_date", sa.Date(), nullable=True, comment="结束日期(NULL=进行中)"),
            sa.Column(
                "status", sa.VARCHAR(20), nullable=False, server_default="active", comment="active/completed/terminated"
            ),
            sa.Column("mentor_score", sa.Numeric(3, 1), nullable=True, comment="带教评分 0-10"),
            sa.Column("mentee_pass_rate", sa.Numeric(5, 2), nullable=True, comment="学员通关率 0-100"),
            sa.Column("notes", sa.TEXT(), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
            sa.UniqueConstraint("tenant_id", "mentor_id", "mentee_id", "start_date", name="uq_mentorship_active"),
        )
        op.create_index("idx_mentorship_tenant", "mentorship_relations", ["tenant_id"])
        op.create_index("idx_mentorship_store_status", "mentorship_relations", ["tenant_id", "store_id", "status"])

        # ─── 4. onboarding_paths — 新员工训练路径 ────────────────────────────────

    if "onboarding_paths" not in existing:
        op.create_table(
            "onboarding_paths",
            sa.Column(
                "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
            ),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("employee_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("template_name", sa.VARCHAR(100), nullable=False, server_default="标准入职路径"),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("target_days", sa.Integer(), nullable=False, server_default="30", comment="目标天数: 7/14/30"),
            sa.Column("current_day", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "tasks",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default="[]",
                comment="[{day,task,type,required,completed,completed_at}]",
            ),
            sa.Column("progress_pct", sa.Numeric(5, 2), nullable=False, server_default="0", comment="完成进度 0-100"),
            sa.Column("mentor_id", postgresql.UUID(as_uuid=True), nullable=True, comment="带教师傅"),
            sa.Column("readiness_score", sa.Numeric(3, 1), server_default="0", comment="上岗准备度 0-10"),
            sa.Column(
                "status",
                sa.VARCHAR(20),
                nullable=False,
                server_default="in_progress",
                comment="in_progress/completed/overdue/terminated",
            ),
            sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        )
        op.create_index("idx_onboarding_tenant", "onboarding_paths", ["tenant_id"])
        op.create_index("idx_onboarding_employee", "onboarding_paths", ["tenant_id", "employee_id"])
        op.create_index("idx_onboarding_store_status", "onboarding_paths", ["tenant_id", "store_id", "status"])

        # ─── 5. position_certifications — 岗位认证记录 ───────────────────────────

    if "position_certifications" not in existing:
        op.create_table(
            "position_certifications",
            sa.Column(
                "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
            ),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("employee_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("position", sa.VARCHAR(50), nullable=False, comment="认证岗位"),
            sa.Column(
                "exam_items",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default="[]",
                comment="[{item,type,score,passed,examiner_id,exam_date}]",
            ),
            sa.Column("total_score", sa.Numeric(5, 2), nullable=True, comment="总分"),
            sa.Column("passed", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("certified_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True, comment="认证有效期"),
            sa.Column("certifier_id", postgresql.UUID(as_uuid=True), nullable=True, comment="认证人ID"),
            sa.Column("retake_count", sa.Integer(), nullable=False, server_default="0", comment="补考次数"),
            sa.Column("notes", sa.TEXT(), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        )
        op.create_index("idx_pos_cert_tenant", "position_certifications", ["tenant_id"])
        op.create_index("idx_pos_cert_employee", "position_certifications", ["tenant_id", "employee_id", "position"])
        op.create_index(
            "idx_pos_cert_store", "position_certifications", ["tenant_id", "store_id", "position", "passed"]
        )

        # ─── 6. store_readiness_scores — 门店就绪度评分 ──────────────────────────

    if "store_readiness_scores" not in existing:
        op.create_table(
            "store_readiness_scores",
            sa.Column(
                "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
            ),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("score_date", sa.Date(), nullable=False),
            sa.Column("shift", sa.VARCHAR(30), nullable=False, server_default="full_day"),
            sa.Column(
                "overall_score", sa.Numeric(5, 2), nullable=False, server_default="0", comment="综合就绪分 0-100"
            ),
            sa.Column(
                "dimensions",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default="{}",
                comment="{shift_coverage,skill_coverage,newbie_ratio,training_completion}",
            ),
            sa.Column("risk_level", sa.VARCHAR(10), nullable=False, server_default="green", comment="green/yellow/red"),
            sa.Column(
                "risk_positions",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default="[]",
                comment="[{position,gap,reason}]",
            ),
            sa.Column(
                "action_items",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default="[]",
                comment="[{action,priority,assigned_to}]",
            ),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
            sa.UniqueConstraint("tenant_id", "store_id", "score_date", "shift", name="uq_readiness_daily"),
        )
        op.create_index("idx_readiness_tenant", "store_readiness_scores", ["tenant_id"])
        op.create_index(
            "idx_readiness_date_risk", "store_readiness_scores", ["tenant_id", sa.text("score_date DESC"), "risk_level"]
        )

        # ─── 7. peak_guard_records — 高峰保障记录 ────────────────────────────────

    if "peak_guard_records" not in existing:
        op.create_table(
            "peak_guard_records",
            sa.Column(
                "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
            ),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("guard_date", sa.Date(), nullable=False),
            sa.Column("peak_type", sa.VARCHAR(20), nullable=False, comment="lunch/dinner/weekend/holiday/event"),
            sa.Column("expected_traffic", sa.Integer(), server_default="0", comment="预计客流"),
            sa.Column("coverage_score", sa.Numeric(5, 2), server_default="0", comment="人力覆盖度 0-100"),
            sa.Column(
                "risk_positions",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default="[]",
                comment="[{position,required,actual,gap}]",
            ),
            sa.Column(
                "actions_taken",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default="[]",
                comment="[{action,executor,result,timestamp}]",
            ),
            sa.Column("result_score", sa.Numeric(5, 2), nullable=True, comment="实际保障评分"),
            sa.Column("notes", sa.TEXT(), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        )
        op.create_index("idx_peak_guard_tenant", "peak_guard_records", ["tenant_id"])
        op.create_index(
            "idx_peak_guard_store_date", "peak_guard_records", ["tenant_id", "store_id", sa.text("guard_date DESC")]
        )
        op.create_index(
            "idx_peak_guard_coverage",
            "peak_guard_records",
            ["tenant_id", "guard_date", "coverage_score"],
            postgresql_where=sa.text("coverage_score < 60"),
        )

        # ─── 8. dri_work_orders — DRI工单 ────────────────────────────────────────

    if "dri_work_orders" not in existing:
        op.create_table(
            "dri_work_orders",
            sa.Column(
                "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
            ),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("order_no", sa.VARCHAR(30), nullable=False, comment="工单编号 auto-gen"),
            sa.Column(
                "order_type", sa.VARCHAR(30), nullable=False, comment="recruit/fill_gap/training/retention/reform"
            ),
            sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("title", sa.VARCHAR(200), nullable=False),
            sa.Column("description", sa.TEXT(), nullable=True),
            sa.Column(
                "severity", sa.VARCHAR(10), nullable=False, server_default="medium", comment="low/medium/high/critical"
            ),
            sa.Column(
                "status",
                sa.VARCHAR(20),
                nullable=False,
                server_default="draft",
                comment="draft/assigned/in_progress/completed/closed/cancelled",
            ),
            sa.Column("dri_user_id", postgresql.UUID(as_uuid=True), nullable=True, comment="DRI负责人"),
            sa.Column(
                "collaborators",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default="[]",
                comment="[{user_id,role}]",
            ),
            sa.Column(
                "actions",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default="[]",
                comment="[{action,assigned_to,due_date,status,result}]",
            ),
            sa.Column("due_date", sa.Date(), nullable=True),
            sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("resolution", sa.TEXT(), nullable=True, comment="解决结果"),
            sa.Column("source", sa.VARCHAR(30), server_default="manual", comment="manual/ai_alert/system"),
            sa.Column("source_ref_id", postgresql.UUID(as_uuid=True), nullable=True, comment="来源引用ID"),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
            sa.UniqueConstraint("tenant_id", "order_no", name="uq_dri_order_no"),
            sa.CheckConstraint(
                "status IN ('draft','assigned','in_progress','completed','closed','cancelled')",
                name="chk_dri_wo_status",
            ),
            sa.CheckConstraint("severity IN ('low','medium','high','critical')", name="chk_dri_wo_severity"),
            sa.CheckConstraint(
                "order_type IN ('recruit','fill_gap','training','retention','reform','new_store')",
                name="chk_dri_wo_order_type",
            ),
        )
        op.create_index("idx_dri_wo_tenant", "dri_work_orders", ["tenant_id"])
        op.create_index("idx_dri_wo_store_status", "dri_work_orders", ["tenant_id", "store_id", "status"])
        op.create_index(
            "idx_dri_wo_active",
            "dri_work_orders",
            ["tenant_id", "status", "due_date"],
            postgresql_where=sa.text("status NOT IN ('completed','closed','cancelled')"),
        )
        op.create_index("idx_dri_wo_dri_user", "dri_work_orders", ["tenant_id", "dri_user_id", "status"])

        # ─── 9. ai_alerts — AI预警记录 ───────────────────────────────────────────

    if "ai_alerts" not in existing:
        op.create_table(
            "ai_alerts",
            sa.Column(
                "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
            ),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "alert_type",
                sa.VARCHAR(30),
                nullable=False,
                comment="turnover/peak_gap/training_lag/schedule_imbalance/new_store_gap",
            ),
            sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("employee_id", postgresql.UUID(as_uuid=True), nullable=True, comment="相关员工(可空)"),
            sa.Column(
                "severity", sa.VARCHAR(10), nullable=False, server_default="warning", comment="info/warning/critical"
            ),
            sa.Column("title", sa.VARCHAR(200), nullable=False),
            sa.Column("detail", sa.TEXT(), nullable=True),
            sa.Column(
                "suggestion",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default="{}",
                comment="{summary,actions:[{action,priority}]}",
            ),
            sa.Column("resolved", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("resolved_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("resolution_note", sa.TEXT(), nullable=True),
            sa.Column("linked_order_id", postgresql.UUID(as_uuid=True), nullable=True, comment="关联DRI工单"),
            sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True, comment="预警有效期"),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
            sa.CheckConstraint(
                "alert_type IN ('turnover','peak_gap','training_lag','schedule_imbalance','new_store_gap')",
                name="chk_ai_alert_type",
            ),
            sa.CheckConstraint("severity IN ('info','warning','critical')", name="chk_ai_alert_severity"),
        )
        op.create_index("idx_ai_alert_tenant", "ai_alerts", ["tenant_id"])
        op.create_index(
            "idx_ai_alert_resolved", "ai_alerts", ["tenant_id", "resolved", "severity", sa.text("created_at DESC")]
        )
        op.create_index("idx_ai_alert_store_type", "ai_alerts", ["tenant_id", "store_id", "alert_type", "resolved"])
        op.create_index(
            "idx_ai_alert_employee",
            "ai_alerts",
            ["tenant_id", "employee_id"],
            postgresql_where=sa.text("employee_id IS NOT NULL"),
        )

        # ─── 10. coach_sessions — 店长教练记录 ───────────────────────────────────

    if "coach_sessions" not in existing:
        op.create_table(
            "coach_sessions",
            sa.Column(
                "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
            ),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("manager_id", postgresql.UUID(as_uuid=True), nullable=False, comment="店长员工ID"),
            sa.Column("session_date", sa.Date(), nullable=False),
            sa.Column(
                "session_type",
                sa.VARCHAR(30),
                nullable=False,
                server_default="daily",
                comment="daily/weekly/monthly/incident",
            ),
            sa.Column(
                "suggestions",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default="[]",
                comment="[{category,content,priority,accepted}]",
            ),
            sa.Column(
                "actions_taken",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default="[]",
                comment="[{action,result,completed_at}]",
            ),
            sa.Column(
                "focus_employees",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default="[]",
                comment="[{employee_id,reason,action}]",
            ),
            sa.Column("readiness_before", sa.Numeric(5, 2), nullable=True, comment="教练前就绪分"),
            sa.Column("readiness_after", sa.Numeric(5, 2), nullable=True, comment="教练后就绪分"),
            sa.Column("notes", sa.TEXT(), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        )
        op.create_index("idx_coach_tenant", "coach_sessions", ["tenant_id"])
        op.create_index(
            "idx_coach_store_date", "coach_sessions", ["tenant_id", "store_id", sa.text("session_date DESC")]
        )
        op.create_index(
            "idx_coach_manager_date", "coach_sessions", ["tenant_id", "manager_id", sa.text("session_date DESC")]
        )

        # ─── RLS 策略（10张表） ──────────────────────────────────────────────────
        for table in TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"""
                CREATE POLICY {table}_tenant_isolation ON {table}
                USING (tenant_id = (current_setting('app.tenant_id', true)::UUID))
            """)


def downgrade() -> None:
    # 先删除所有 RLS 策略
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")

    # 按创建反序删除表（含索引自动级联删除）
    for table in reversed(TABLES):
        op.drop_table(table)
