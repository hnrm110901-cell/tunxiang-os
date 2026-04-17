"""D11 Should-Fix P1 — 考试系统（题库/试卷/证书 + 考试记录扩展）

新增表：
  - exam_questions  题库
  - exam_papers     试卷
  - exam_certificates 证书

扩展已有表 exam_attempts：
  - paper_id (FK → exam_papers.id, nullable)
  - started_at / submitted_at / duration_sec
  - status（in_progress/submitted/graded/expired）
  - exam_id 放宽为 nullable 以兼容新流程

Revision ID: z63_d11_exam_system
Revises: z62_merge_mustfix_p0
Create Date: 2026-04-17
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID


revision = "z63_d11_exam_system"
down_revision = "z62_merge_mustfix_p0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) exam_questions
    op.create_table(
        "exam_questions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("course_id", UUID(as_uuid=True), sa.ForeignKey("training_courses.id"), nullable=False, index=True),
        sa.Column("type", sa.String(20), nullable=False, server_default="single"),
        sa.Column("stem", sa.Text, nullable=False),
        sa.Column("options_json", JSON, nullable=True),
        sa.Column("correct_answer_json", JSON, nullable=True),
        sa.Column("score", sa.Integer, nullable=False, server_default="5"),
        sa.Column("difficulty", sa.Integer, nullable=False, server_default="3"),
        sa.Column("explanation", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # 2) exam_papers
    op.create_table(
        "exam_papers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("course_id", UUID(as_uuid=True), sa.ForeignKey("training_courses.id"), nullable=False, index=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("total_score", sa.Integer, nullable=False, server_default="100"),
        sa.Column("pass_score", sa.Integer, nullable=False, server_default="60"),
        sa.Column("duration_min", sa.Integer, nullable=False, server_default="30"),
        sa.Column("question_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("question_ids_json", JSON, nullable=False),
        sa.Column("is_random", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_by", sa.String(50), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # 3) exam_certificates
    op.create_table(
        "exam_certificates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", sa.String(50), nullable=False, index=True),
        sa.Column("course_id", UUID(as_uuid=True), sa.ForeignKey("training_courses.id"), nullable=False, index=True),
        sa.Column("attempt_id", UUID(as_uuid=True), sa.ForeignKey("exam_attempts.id"), nullable=True),
        sa.Column("cert_no", sa.String(64), nullable=False, index=True),
        sa.Column("issued_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("expire_at", sa.DateTime, nullable=True),
        sa.Column("pdf_url", sa.String(500), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("employee_id", "course_id", "cert_no", name="uq_exam_cert"),
    )

    # 4) 扩展 exam_attempts
    with op.batch_alter_table("exam_attempts") as batch:
        batch.alter_column("exam_id", existing_type=UUID(as_uuid=True), nullable=True)
        batch.add_column(sa.Column("paper_id", UUID(as_uuid=True), nullable=True))
        batch.add_column(sa.Column("started_at", sa.DateTime, nullable=True))
        batch.add_column(sa.Column("submitted_at", sa.DateTime, nullable=True))
        batch.add_column(sa.Column("duration_sec", sa.Integer, nullable=True))
        batch.add_column(sa.Column("status", sa.String(20), nullable=False, server_default="in_progress"))
    op.create_foreign_key(
        "fk_exam_attempts_paper", "exam_attempts", "exam_papers", ["paper_id"], ["id"]
    )
    op.create_index("ix_exam_attempts_paper_id", "exam_attempts", ["paper_id"])


def downgrade() -> None:
    op.drop_index("ix_exam_attempts_paper_id", table_name="exam_attempts")
    op.drop_constraint("fk_exam_attempts_paper", "exam_attempts", type_="foreignkey")
    with op.batch_alter_table("exam_attempts") as batch:
        batch.drop_column("status")
        batch.drop_column("duration_sec")
        batch.drop_column("submitted_at")
        batch.drop_column("started_at")
        batch.drop_column("paper_id")
        batch.alter_column("exam_id", existing_type=UUID(as_uuid=True), nullable=False)

    op.drop_table("exam_certificates")
    op.drop_table("exam_papers")
    op.drop_table("exam_questions")
