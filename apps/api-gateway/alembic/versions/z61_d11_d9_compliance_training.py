"""z61 — D11+D9 合规证照 Must-Fix P0

覆盖三个任务的 schema 变更：

Task 1 (D11 健康证):
  - health_certificates 表已存在（见 .models/health_certificate.py），本次补齐：
    · 确保复合索引 (store_id, expiry_date) 以加速扫描
    · 确保 status 字段有索引
  （若索引已存在则 IF NOT EXISTS 静默跳过）

Task 2 (D9 劳动合同):
  - employee_contracts 表已存在（见 .models/employee_contract.py），本次补齐：
    · 添加 (store_id, end_date) 复合索引加速到期扫描

Task 3 (D11 培训课件存储基础):
  - 新建 training_materials 表（课程 → 课件）
    字段：id UUID PK, course_id FK, title, material_type, file_url,
          file_size_bytes, duration_seconds, text_content,
          sort_order, is_required, is_active, created_at, updated_at

Revision ID: z61_compliance_training
Revises: z60_d1_d4_pos_crm_menu_tables
Create Date: 2026-04-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "z61_compliance_training"
down_revision = "z60_d1_d4_pos_crm_menu_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Task 3: training_materials ───────────────────────────────────
    op.create_table(
        "training_materials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("material_type", sa.String(length=20), nullable=False, server_default="video"),
        sa.Column("file_url", sa.String(length=500), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["course_id"], ["training_courses.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_training_materials_course_id", "training_materials", ["course_id"], unique=False
    )

    # ── Task 1: 健康证扫描索引（幂等：IF NOT EXISTS）─────────────────
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_health_certs_store_expiry "
        "ON health_certificates (store_id, expiry_date)"
    )

    # ── Task 2: 劳动合同扫描索引 ────────────────────────────────────
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_employee_contracts_store_end_date "
        "ON employee_contracts (store_id, end_date)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_employee_contracts_store_end_date")
    op.execute("DROP INDEX IF EXISTS ix_health_certs_store_expiry")
    op.drop_index("ix_training_materials_course_id", table_name="training_materials")
    op.drop_table("training_materials")
