"""
TunxiangOS Smart Table Card - Database Migration
Alembic migration for smart table card feature.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "003_add_smart_table_card"
down_revision = "002_base_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create tables and indices for smart table card feature."""
    op.create_table(
        "tables",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.func.gen_random_uuid()),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("table_no", sa.String(50), nullable=False),
        sa.Column("area", sa.String(100), nullable=True),
        sa.Column("seats", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("status", sa.String(20), nullable=False, server_default="empty", index=True),
        sa.Column("guest_count", sa.Integer(), nullable=True),
        sa.Column("seated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checkout_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false", index=True),
        sa.Column("config", postgresql.JSONB(), nullable=True, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "store_id", "table_no", name="uq_tables_tenant_store_no"),
    )
    op.create_index("idx_tables_tenant_store_status", "tables", ["tenant_id", "store_id", "status"])
    op.execute("ALTER TABLE tables ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tables_tenant_isolation ON tables USING (tenant_id = current_setting('app.tenant_id')::uuid)")
    op.execute("""CREATE OR REPLACE FUNCTION update_tables_updated_at() RETURNS TRIGGER AS $$ BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$ LANGUAGE plpgsql""")
    op.execute("""CREATE TRIGGER tables_updated_at_trigger BEFORE UPDATE ON tables FOR EACH ROW EXECUTE FUNCTION update_tables_updated_at()""")

    op.create_table(
        "table_card_click_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.func.gen_random_uuid()),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("table_no", sa.String(50), nullable=False),
        sa.Column("field_key", sa.String(100), nullable=False, index=True),
        sa.Column("clicked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("meal_period", sa.String(50), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("score", sa.Float(), nullable=True, server_default="1.0"),
        sa.Column("metadata", postgresql.JSONB(), nullable=True, server_default="{}"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false", index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_click_logs_tenant_store_field", "table_card_click_logs", ["tenant_id", "store_id", "field_key"])
    op.create_index("idx_click_logs_clicked_at", "table_card_click_logs", ["clicked_at"])
    op.execute("ALTER TABLE table_card_click_logs ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY click_logs_tenant_isolation ON table_card_click_logs USING (tenant_id = current_setting('app.tenant_id')::uuid)")


def downgrade() -> None:
    """Drop tables and related objects."""
    op.execute("DROP POLICY IF EXISTS click_logs_tenant_isolation ON table_card_click_logs")
    op.execute("DROP POLICY IF EXISTS tables_tenant_isolation ON tables")
    op.execute("DROP TRIGGER IF EXISTS tables_updated_at_trigger ON tables")
    op.execute("DROP FUNCTION IF EXISTS update_tables_updated_at()")
    op.drop_table("table_card_click_logs")
    op.drop_table("tables")
