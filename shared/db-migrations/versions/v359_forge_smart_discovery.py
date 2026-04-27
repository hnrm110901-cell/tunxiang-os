"""v359: forge_search_intents + forge_app_embeddings + forge_app_combos for Forge v2.0 Agent Exchange.

智能发现——搜索意图日志、应用向量嵌入（pgvector）、应用组合推荐。

Revision ID: v359_forge_smart_discovery
Revises: v358_forge_token_meters
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "v359_forge_smart_discovery"
down_revision: Union[str, None] = "v358_forge_token_meters"
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
    # --- forge_search_intents ---
    op.create_table(
        "forge_search_intents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("query_text", sa.Text, nullable=False),
        sa.Column("parsed_intents", sa.JSON, server_default=sa.text("'[]'::jsonb")),
        sa.Column("matched_app_ids", sa.JSON, server_default=sa.text("'[]'::jsonb")),
        sa.Column("result_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("clicked_app_id", sa.String(50)),
        sa.Column("search_duration_ms", sa.Integer, server_default=sa.text("0")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
    )
    op.create_index(
        "ix_forge_search_intents_created",
        "forge_search_intents",
        [sa.text("created_at DESC")],
    )
    _enable_rls("forge_search_intents")

    # --- forge_app_embeddings (requires pgvector) ---
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "forge_app_embeddings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("app_id", sa.String(50), nullable=False, unique=True),
        sa.Column("embedding_model", sa.String(100), server_default="text-embedding-3-small"),
        sa.Column("description_text", sa.Text),
        sa.Column("last_updated", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
    )
    # Add vector column via raw SQL (SQLAlchemy doesn't have native pgvector type)
    op.execute("ALTER TABLE forge_app_embeddings ADD COLUMN embedding vector(1536)")
    _enable_rls("forge_app_embeddings")

    # --- forge_app_combos ---
    op.create_table(
        "forge_app_combos",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("combo_id", sa.String(50), nullable=False, unique=True),
        sa.Column("combo_name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("app_ids", sa.JSON, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("use_case", sa.String(200), server_default=""),
        sa.Column("target_role", sa.String(50), server_default=""),
        sa.Column("synergy_score", sa.Numeric(5, 2), server_default=sa.text("0")),
        sa.Column("evidence", sa.JSON, server_default=sa.text("'{}'::jsonb")),
        sa.Column("install_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.text("false")),
    )
    op.create_index(
        "ix_forge_app_combos_target_role",
        "forge_app_combos",
        ["target_role"],
    )
    op.create_index(
        "ix_forge_app_combos_synergy_score",
        "forge_app_combos",
        [sa.text("synergy_score DESC")],
    )
    _enable_rls("forge_app_combos")


def downgrade() -> None:
    _disable_rls("forge_app_combos")
    op.drop_table("forge_app_combos")
    _disable_rls("forge_app_embeddings")
    op.drop_table("forge_app_embeddings")
    _disable_rls("forge_search_intents")
    op.drop_table("forge_search_intents")
    op.execute("DROP EXTENSION IF EXISTS vector")
