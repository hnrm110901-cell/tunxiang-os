"""v362: forge_auto_reviews + forge_review_templates for Forge v2.5.

AI自动审核结果 + 审核模板（按应用类型）。

Revision ID: v362_forge_auto_review
Revises: v361_forge_builder
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "v362_forge_auto_review"
down_revision: Union[str, None] = "v361_forge_builder"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS_CONDITION = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID"
)


def _enable_rls(table_name: str) -> None:
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    for action, clause in [
        ("select", f"FOR SELECT USING ({_RLS_CONDITION})"),
        ("insert", f"FOR INSERT WITH CHECK ({_RLS_CONDITION})"),
        ("update", f"FOR UPDATE USING ({_RLS_CONDITION}) WITH CHECK ({_RLS_CONDITION})"),
        ("delete", f"FOR DELETE USING ({_RLS_CONDITION})"),
    ]:
        op.execute(
            f"CREATE POLICY {table_name}_rls_{action} ON {table_name} "
            f"AS PERMISSIVE {clause}"
        )


def _disable_rls(table_name: str) -> None:
    for suffix in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS {table_name}_rls_{suffix} ON {table_name}")
    op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    # --- forge_auto_reviews ---
    op.create_table(
        "forge_auto_reviews",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("review_id", sa.String(50), nullable=False),
        sa.Column("app_id", sa.String(50), nullable=False),
        sa.Column("auto_checks", sa.JSON, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("ai_suggestions", sa.JSON, server_default=sa.text("'[]'::jsonb")),
        sa.Column("human_required", sa.JSON, server_default=sa.text("'[]'::jsonb")),
        sa.Column("auto_pass_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("auto_fail_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("total_checks", sa.Integer, server_default=sa.text("0")),
        sa.Column("auto_score", sa.Integer, server_default=sa.text("0")),
        sa.Column("duration_ms", sa.Integer, server_default=sa.text("0")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
    )
    op.create_index(
        "ix_forge_auto_reviews_app_created",
        "forge_auto_reviews",
        ["app_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_forge_auto_reviews_score",
        "forge_auto_reviews",
        ["auto_score"],
    )
    _enable_rls("forge_auto_reviews")

    # --- forge_review_templates ---
    op.create_table(
        "forge_review_templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("template_id", sa.String(50), nullable=False, unique=True),
        sa.Column("app_category", sa.String(50), nullable=False),
        sa.Column("template_name", sa.String(200), nullable=False),
        sa.Column("auto_checks", sa.JSON, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("human_checks", sa.JSON, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("pass_threshold", sa.Integer, server_default=sa.text("80")),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
    )
    op.create_index(
        "ix_forge_review_templates_category",
        "forge_review_templates",
        ["app_category"],
    )
    _enable_rls("forge_review_templates")


def downgrade() -> None:
    _disable_rls("forge_review_templates")
    op.drop_table("forge_review_templates")
    _disable_rls("forge_auto_reviews")
    op.drop_table("forge_auto_reviews")
