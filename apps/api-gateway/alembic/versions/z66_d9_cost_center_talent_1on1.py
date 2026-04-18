"""z66 — D9 成本中心 + 九宫格人才盘点 + 1-on-1 面谈

新增 10 张表：
  成本中心:  cost_centers / employee_cost_centers / cost_center_budgets
  人才盘点:  talent_assessments / talent_pools / succession_plans
  1-on-1:   one_on_one_templates / one_on_one_meetings / one_on_one_follow_ups
  预留:      pulse_surveys

Revision ID: z66_d9_cost_center_talent_1on1
Revises: z65_d5_d7_closing_access
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers, used by Alembic.
revision = "z66_d9_cost_center_talent_1on1"
down_revision = "z65_d5_d7_closing_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── cost_centers ──────────────────────────────
    op.create_table(
        "cost_centers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False, index=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("category", sa.String(30), nullable=False, index=True),
        sa.Column("parent_id", UUID(as_uuid=True), sa.ForeignKey("cost_centers.id"), nullable=True, index=True),
        sa.Column("store_id", sa.String(50), nullable=True, index=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("uq_cc_store_code", "cost_centers", ["store_id", "code"], unique=True)

    # ─── employee_cost_centers ─────────────────────
    op.create_table(
        "employee_cost_centers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", sa.String(50), sa.ForeignKey("employees.id"), nullable=False, index=True),
        sa.Column("cost_center_id", UUID(as_uuid=True), sa.ForeignKey("cost_centers.id"), nullable=False, index=True),
        sa.Column("allocation_pct", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("uq_emp_cc_from", "employee_cost_centers", ["employee_id", "cost_center_id", "effective_from"], unique=True)

    # ─── cost_center_budgets ───────────────────────
    op.create_table(
        "cost_center_budgets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("cost_center_id", UUID(as_uuid=True), sa.ForeignKey("cost_centers.id"), nullable=False, index=True),
        sa.Column("year_month", sa.String(7), nullable=False, index=True),
        sa.Column("labor_budget_fen", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("revenue_target_fen", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("actual_labor_fen", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("uq_ccb_cc_ym", "cost_center_budgets", ["cost_center_id", "year_month"], unique=True)

    # ─── talent_assessments ────────────────────────
    op.create_table(
        "talent_assessments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", sa.String(50), sa.ForeignKey("employees.id"), nullable=False, index=True),
        sa.Column("assessor_id", sa.String(50), nullable=False, index=True),
        sa.Column("assessment_date", sa.Date(), nullable=False, index=True),
        sa.Column("performance_score", sa.Integer(), nullable=False),
        sa.Column("potential_score", sa.Integer(), nullable=False),
        sa.Column("nine_box_cell", sa.Integer(), nullable=False, index=True),
        sa.Column("strengths", sa.Text(), nullable=True),
        sa.Column("development_areas", sa.Text(), nullable=True),
        sa.Column("career_path", sa.Text(), nullable=True),
        sa.Column("ai_development_plan", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft", index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ─── talent_pools ──────────────────────────────
    op.create_table(
        "talent_pools",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", sa.String(50), sa.ForeignKey("employees.id"), nullable=False, index=True),
        sa.Column("pool_type", sa.String(30), nullable=False, index=True),
        sa.Column("target_position", sa.String(100), nullable=True),
        sa.Column("readiness", sa.String(20), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active", index=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("added_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ─── succession_plans ──────────────────────────
    op.create_table(
        "succession_plans",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("key_position_id", sa.String(100), nullable=False, index=True),
        sa.Column("current_holder_id", sa.String(50), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("successor_id", sa.String(50), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("readiness", sa.String(20), nullable=True),
        sa.Column("gap_analysis", sa.Text(), nullable=True),
        sa.Column("development_plan", sa.Text(), nullable=True),
        sa.Column("candidates_json", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ─── one_on_one_templates ──────────────────────
    op.create_table(
        "one_on_one_templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("topic_category", sa.String(30), nullable=False, index=True),
        sa.Column("questions_json", JSONB, nullable=False, server_default="[]"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ─── one_on_one_meetings ───────────────────────
    op.create_table(
        "one_on_one_meetings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("initiator_id", sa.String(50), sa.ForeignKey("employees.id"), nullable=False, index=True),
        sa.Column("participant_id", sa.String(50), sa.ForeignKey("employees.id"), nullable=False, index=True),
        sa.Column("template_id", UUID(as_uuid=True), sa.ForeignKey("one_on_one_templates.id"), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("duration_min", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("location", sa.String(200), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="scheduled", index=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("action_items_json", JSONB, nullable=True),
        sa.Column("follow_up_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ─── one_on_one_follow_ups ─────────────────────
    op.create_table(
        "one_on_one_follow_ups",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("meeting_id", UUID(as_uuid=True), sa.ForeignKey("one_on_one_meetings.id"), nullable=False, index=True),
        sa.Column("action_item", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.String(50), sa.ForeignKey("employees.id"), nullable=False, index=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending", index=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ─── 预留: pulse_surveys ───────────────────────
    op.create_table(
        "pulse_surveys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("store_id", sa.String(50), nullable=False, index=True),
        sa.Column("survey_date", sa.Date(), nullable=False, index=True),
        sa.Column("employee_id", sa.String(50), sa.ForeignKey("employees.id"), nullable=False, index=True),
        sa.Column("mood_score", sa.Integer(), nullable=True),  # 1-5
        sa.Column("engagement_score", sa.Integer(), nullable=True),  # 1-5
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("pulse_surveys")
    op.drop_table("one_on_one_follow_ups")
    op.drop_table("one_on_one_meetings")
    op.drop_table("one_on_one_templates")
    op.drop_table("succession_plans")
    op.drop_table("talent_pools")
    op.drop_table("talent_assessments")
    op.drop_index("uq_ccb_cc_ym", table_name="cost_center_budgets")
    op.drop_table("cost_center_budgets")
    op.drop_index("uq_emp_cc_from", table_name="employee_cost_centers")
    op.drop_table("employee_cost_centers")
    op.drop_index("uq_cc_store_code", table_name="cost_centers")
    op.drop_table("cost_centers")
