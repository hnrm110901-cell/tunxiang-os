"""z68 — D11 OKR + E-learning + Pulse Survey

新增 11 张表：
  OKR:        okr_objectives / okr_key_results / okr_updates / okr_alignments
  E-learning: learning_paths / learning_path_enrollments / learning_points / learning_achievements
  Pulse:      pulse_survey_templates / pulse_survey_instances / pulse_survey_responses

Revision ID: z68_d11_okr_elearning_pulse
Revises: z67_merge_wave4
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers, used by Alembic.
revision = "z68_d11_okr_elearning_pulse"
down_revision = "z67_merge_wave4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── okr_objectives ────────────────────────────
    op.create_table(
        "okr_objectives",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", sa.String(50), nullable=False, index=True),
        sa.Column("owner_type", sa.String(20), nullable=False, server_default="personal", index=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("period", sa.String(20), nullable=False, index=True),
        sa.Column("parent_objective_id", UUID(as_uuid=True), sa.ForeignKey("okr_objectives.id"), nullable=True, index=True),
        sa.Column("target_value", sa.Numeric(18, 2), nullable=True),
        sa.Column("actual_value", sa.Numeric(18, 2), nullable=True),
        sa.Column("weight", sa.Integer(), server_default="100"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft", index=True),
        sa.Column("progress_pct", sa.Numeric(5, 2), server_default="0"),
        sa.Column("health", sa.String(10), server_default="green", index=True),
        sa.Column("store_id", sa.String(50), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ─── okr_key_results ───────────────────────────
    op.create_table(
        "okr_key_results",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("objective_id", UUID(as_uuid=True), sa.ForeignKey("okr_objectives.id"), nullable=False, index=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("metric_type", sa.String(20), nullable=False, server_default="numeric"),
        sa.Column("start_value", sa.Numeric(18, 2), server_default="0"),
        sa.Column("target_value", sa.Numeric(18, 2), nullable=False),
        sa.Column("current_value", sa.Numeric(18, 2), server_default="0"),
        sa.Column("unit", sa.String(20), nullable=True),
        sa.Column("weight", sa.Integer(), server_default="100"),
        sa.Column("owner_id", sa.String(50), nullable=True, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active", index=True),
        sa.Column("progress_pct", sa.Numeric(5, 2), server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ─── okr_updates ───────────────────────────────
    op.create_table(
        "okr_updates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("key_result_id", UUID(as_uuid=True), sa.ForeignKey("okr_key_results.id"), nullable=False, index=True),
        sa.Column("value", sa.Numeric(18, 2), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("evidence_url", sa.String(500), nullable=True),
        sa.Column("updated_by", sa.String(50), nullable=False, index=True),
        sa.Column("updated_at_ts", sa.DateTime(), nullable=False, server_default=sa.func.now(), index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ─── okr_alignments ────────────────────────────
    op.create_table(
        "okr_alignments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("parent_objective_id", UUID(as_uuid=True), sa.ForeignKey("okr_objectives.id"), nullable=False, index=True),
        sa.Column("child_objective_id", UUID(as_uuid=True), sa.ForeignKey("okr_objectives.id"), nullable=False, index=True),
        sa.Column("alignment_type", sa.String(20), nullable=False, server_default="contribute_to"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("extra_json", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("uq_okr_alignment_pair", "okr_alignments", ["parent_objective_id", "child_objective_id"], unique=True)

    # ─── learning_paths ────────────────────────────
    op.create_table(
        "learning_paths",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("target_position_id", sa.String(100), nullable=True, index=True),
        sa.Column("required_courses_json", JSONB, nullable=False, server_default="[]"),
        sa.Column("estimated_hours", sa.Integer(), server_default="0"),
        sa.Column("created_by", sa.String(50), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ─── learning_path_enrollments ─────────────────
    op.create_table(
        "learning_path_enrollments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("path_id", UUID(as_uuid=True), sa.ForeignKey("learning_paths.id"), nullable=False, index=True),
        sa.Column("employee_id", sa.String(50), nullable=False, index=True),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("progress_pct", sa.Integer(), server_default="0"),
        sa.Column("current_course_id", sa.String(100), nullable=True),
        sa.Column("completed_courses_json", JSONB, nullable=False, server_default="[]"),
        sa.Column("status", sa.String(20), nullable=False, server_default="not_started", index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("uq_lp_enroll", "learning_path_enrollments", ["path_id", "employee_id"], unique=True)

    # ─── learning_points ───────────────────────────
    op.create_table(
        "learning_points",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", sa.String(50), nullable=False, index=True),
        sa.Column("store_id", sa.String(50), nullable=True, index=True),
        sa.Column("event_type", sa.String(30), nullable=False, index=True),
        sa.Column("points_value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_id", sa.String(100), nullable=True),
        sa.Column("awarded_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), index=True),
        sa.Column("awarded_by", sa.String(50), nullable=True),
        sa.Column("remark", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ─── learning_achievements ─────────────────────
    op.create_table(
        "learning_achievements",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", sa.String(50), nullable=False, index=True),
        sa.Column("badge_code", sa.String(50), nullable=False, index=True),
        sa.Column("badge_name", sa.String(100), nullable=False),
        sa.Column("earned_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("source_path_id", UUID(as_uuid=True), sa.ForeignKey("learning_paths.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("uq_la_emp_badge", "learning_achievements", ["employee_id", "badge_code"], unique=True)

    # ─── pulse_survey_templates ────────────────────
    op.create_table(
        "pulse_survey_templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("frequency", sa.String(20), nullable=False, server_default="monthly"),
        sa.Column("questions_json", JSONB, nullable=False, server_default="[]"),
        sa.Column("target_scope", sa.String(20), nullable=False, server_default="all"),
        sa.Column("target_filter_json", JSONB, nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allow_anonymous", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ─── pulse_survey_instances ────────────────────
    op.create_table(
        "pulse_survey_instances",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("template_id", UUID(as_uuid=True), sa.ForeignKey("pulse_survey_templates.id"), nullable=False, index=True),
        sa.Column("store_id", sa.String(50), nullable=True, index=True),
        sa.Column("scheduled_date", sa.Date(), nullable=False, index=True),
        sa.Column("target_employee_ids_json", JSONB, nullable=False, server_default="[]"),
        sa.Column("status", sa.String(20), nullable=False, server_default="scheduled", index=True),
        sa.Column("response_deadline", sa.DateTime(), nullable=True),
        sa.Column("sent_count", sa.Integer(), server_default="0"),
        sa.Column("response_count", sa.Integer(), server_default="0"),
        sa.Column("summary_json", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ─── pulse_survey_responses ────────────────────
    op.create_table(
        "pulse_survey_responses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("instance_id", UUID(as_uuid=True), sa.ForeignKey("pulse_survey_instances.id"), nullable=False, index=True),
        sa.Column("employee_id", sa.String(50), nullable=True, index=True),
        sa.Column("employee_hash", sa.String(64), nullable=True, index=True),
        sa.Column("is_anonymous", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("responses_json", JSONB, nullable=False, server_default="[]"),
        sa.Column("sentiment_score", sa.Numeric(4, 2), nullable=True),
        sa.Column("sentiment_label", sa.String(20), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("pulse_survey_responses")
    op.drop_table("pulse_survey_instances")
    op.drop_table("pulse_survey_templates")
    op.drop_index("uq_la_emp_badge", table_name="learning_achievements")
    op.drop_table("learning_achievements")
    op.drop_table("learning_points")
    op.drop_index("uq_lp_enroll", table_name="learning_path_enrollments")
    op.drop_table("learning_path_enrollments")
    op.drop_table("learning_paths")
    op.drop_index("uq_okr_alignment_pair", table_name="okr_alignments")
    op.drop_table("okr_alignments")
    op.drop_table("okr_updates")
    op.drop_table("okr_key_results")
    op.drop_table("okr_objectives")
