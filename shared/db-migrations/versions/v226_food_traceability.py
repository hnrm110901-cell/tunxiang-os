"""食安追溯 — trace_suppliers + trace_inbound_records + trace_coldchain_logs
Revision: v226
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v226"
down_revision = "v225"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- trace_suppliers 供应商资质档案 ---
    op.create_table(
        "trace_suppliers",
        sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("supplier_name", sa.String(200), nullable=False),
        sa.Column("license_no", sa.String(100)),
        sa.Column("license_type", sa.String(50)),
        sa.Column("contact_name", sa.String(50)),
        sa.Column("contact_phone", sa.String(20)),
        sa.Column("address", sa.Text()),
        sa.Column("certs", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column("valid_until", sa.Date()),
        sa.Column("verification_status", sa.String(20), server_default=sa.text("'pending'")),
        sa.Column("verified_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("tenant_id", postgresql.UUID(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
    )
    op.create_index("ix_ts_tenant", "trace_suppliers", ["tenant_id"])
    op.create_index("ix_ts_license", "trace_suppliers", ["tenant_id", "license_no"])
    _add_rls("trace_suppliers", "ts")

    # --- trace_inbound_records 进货台账 ---
    op.create_table(
        "trace_inbound_records",
        sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("store_id", postgresql.UUID(), nullable=False),
        sa.Column("supplier_id", postgresql.UUID()),
        sa.Column("supplier_name", sa.String(200)),
        sa.Column("product_name", sa.String(200), nullable=False),
        sa.Column("product_category", sa.String(50)),
        sa.Column("batch_no", sa.String(100)),
        sa.Column("quantity", sa.Numeric(10, 2), nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("production_date", sa.Date()),
        sa.Column("expiry_date", sa.Date()),
        sa.Column("origin_trace_code", sa.String(100)),
        sa.Column("storage_type", sa.String(20)),
        sa.Column("inspection_result", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("inspector_id", postgresql.UUID()),
        sa.Column("inspection_notes", sa.Text()),
        sa.Column("received_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("submitted_to_platform", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("submission_id", postgresql.UUID()),
        sa.Column("tenant_id", postgresql.UUID(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
    )
    op.create_index("ix_tir_tenant_store", "trace_inbound_records", ["tenant_id", "store_id"])
    op.create_index("ix_tir_batch", "trace_inbound_records", ["tenant_id", "batch_no"])
    op.create_index("ix_tir_date", "trace_inbound_records", ["tenant_id", "store_id", "received_at"])
    _add_rls("trace_inbound_records", "tir")

    # --- trace_coldchain_logs 冷链温控记录 ---
    op.create_table(
        "trace_coldchain_logs",
        sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("store_id", postgresql.UUID(), nullable=False),
        sa.Column("batch_id", postgresql.UUID()),
        sa.Column("device_id", sa.String(100)),
        sa.Column("checkpoint", sa.String(30), nullable=False),
        sa.Column("temperature_c", sa.Numeric(5, 2), nullable=False),
        sa.Column("humidity_pct", sa.Numeric(5, 2)),
        sa.Column("recorded_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_compliant", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("alert_triggered", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("operator_id", postgresql.UUID()),
        sa.Column("notes", sa.Text()),
        sa.Column("tenant_id", postgresql.UUID(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
    )
    op.create_index("ix_tcl_tenant_store", "trace_coldchain_logs", ["tenant_id", "store_id"])
    op.create_index("ix_tcl_batch", "trace_coldchain_logs", ["tenant_id", "batch_id"])
    _add_rls("trace_coldchain_logs", "tcl")


def _add_rls(table: str, prefix: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY {prefix}_tenant ON {table}
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)


def downgrade() -> None:
    op.drop_table("trace_coldchain_logs")
    op.drop_table("trace_inbound_records")
    op.drop_table("trace_suppliers")
