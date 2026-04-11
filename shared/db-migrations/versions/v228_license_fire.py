"""证照 + 消防 — store_licenses + employee_health_certs + fire_equipment + fire_inspection_logs
Revision: v228
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v228"
down_revision = "v227"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- store_licenses 门店证照库 ---
    op.create_table(
        "store_licenses",
        sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("store_id", postgresql.UUID(), nullable=False),
        sa.Column("license_type", sa.String(50), nullable=False),
        sa.Column("license_no", sa.String(200), nullable=False),
        sa.Column("license_name", sa.String(200)),
        sa.Column("issue_date", sa.Date()),
        sa.Column("expiry_date", sa.Date()),
        sa.Column("issuing_authority", sa.String(200)),
        sa.Column("document_urls", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column("renewal_status", sa.String(20), server_default=sa.text("'valid'")),
        sa.Column("auto_alert_days", sa.Integer(), server_default=sa.text("30")),
        sa.Column("last_alert_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("scope_desc", sa.Text()),
        sa.Column("tenant_id", postgresql.UUID(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
    )
    op.create_index("ix_sl_tenant_store", "store_licenses", ["tenant_id", "store_id"])
    op.create_index("ix_sl_expiry", "store_licenses", ["tenant_id", "expiry_date"])
    op.create_index("ix_sl_type", "store_licenses", ["tenant_id", "license_type"])
    _add_rls("store_licenses", "sl")

    # --- employee_health_certs 员工健康证 ---
    op.create_table(
        "employee_health_certs",
        sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("store_id", postgresql.UUID(), nullable=False),
        sa.Column("employee_id", postgresql.UUID(), nullable=False),
        sa.Column("employee_name", sa.String(50)),
        sa.Column("cert_no", sa.String(100)),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column("issuing_authority", sa.String(200)),
        sa.Column("document_url", sa.String(500)),
        sa.Column("verification_status", sa.String(20), server_default=sa.text("'pending'")),
        sa.Column("verified_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("alert_sent", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("tenant_id", postgresql.UUID(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
    )
    op.create_index("ix_ehc_tenant_store", "employee_health_certs", ["tenant_id", "store_id"])
    op.create_index("ix_ehc_employee", "employee_health_certs", ["tenant_id", "employee_id"])
    op.create_index("ix_ehc_expiry", "employee_health_certs", ["tenant_id", "expiry_date"])
    _add_rls("employee_health_certs", "ehc")

    # --- fire_equipment 消防设备台账 ---
    op.create_table(
        "fire_equipment",
        sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("store_id", postgresql.UUID(), nullable=False),
        sa.Column("equipment_type", sa.String(50), nullable=False),
        sa.Column("equipment_name", sa.String(100)),
        sa.Column("location_desc", sa.String(200)),
        sa.Column("serial_no", sa.String(100)),
        sa.Column("manufacturer", sa.String(100)),
        sa.Column("install_date", sa.Date()),
        sa.Column("last_inspection_date", sa.Date()),
        sa.Column("next_inspection_date", sa.Date()),
        sa.Column("inspection_cycle_days", sa.Integer(), server_default=sa.text("30")),
        sa.Column("status", sa.String(20), server_default=sa.text("'normal'")),
        sa.Column("iot_device_id", sa.String(100)),
        sa.Column("tenant_id", postgresql.UUID(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
    )
    op.create_index("ix_fe_tenant_store", "fire_equipment", ["tenant_id", "store_id"])
    op.create_index("ix_fe_inspection", "fire_equipment", ["tenant_id", "next_inspection_date"])
    _add_rls("fire_equipment", "fe")

    # --- fire_inspection_logs 消防巡检记录 ---
    op.create_table(
        "fire_inspection_logs",
        sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("store_id", postgresql.UUID(), nullable=False),
        sa.Column("inspector_id", postgresql.UUID()),
        sa.Column("inspector_name", sa.String(50)),
        sa.Column("inspection_type", sa.String(30), server_default=sa.text("'routine'")),
        sa.Column("checklist_results", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("issues_found", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column("overall_result", sa.String(20), server_default=sa.text("'pass'")),
        sa.Column("inspected_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("next_scheduled", sa.Date()),
        sa.Column("tenant_id", postgresql.UUID(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
    )
    op.create_index("ix_fil_tenant_store", "fire_inspection_logs", ["tenant_id", "store_id"])
    _add_rls("fire_inspection_logs", "fil")


def _add_rls(table: str, prefix: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY {prefix}_tenant ON {table}
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)


def downgrade() -> None:
    op.drop_table("fire_inspection_logs")
    op.drop_table("fire_equipment")
    op.drop_table("employee_health_certs")
    op.drop_table("store_licenses")
