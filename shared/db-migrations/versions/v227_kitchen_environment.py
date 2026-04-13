"""明厨亮灶 + 环保 — kitchen_devices + kitchen_ai_alerts + env_emission_records + env_waste_disposal
Revision: v227
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v227"
down_revision = "v226"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()

    def _add_rls(table: str, prefix: str) -> None:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='{table}' AND policyname='{prefix}_tenant') THEN
                    EXECUTE 'CREATE POLICY {prefix}_tenant ON {table}
                        USING (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::UUID)
                        WITH CHECK (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::UUID)';
                END IF;
            END$$;
        """)



    # --- kitchen_devices 明厨亮灶设备 ---

    if 'kitchen_devices' not in existing:
        op.create_table(
            "kitchen_devices",
            sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
            sa.Column("store_id", postgresql.UUID(), nullable=False),
            sa.Column("device_name", sa.String(100), nullable=False),
            sa.Column("device_type", sa.String(30), nullable=False),
            sa.Column("device_brand", sa.String(50)),
            sa.Column("device_model", sa.String(50)),
            sa.Column("serial_no", sa.String(100)),
            sa.Column("stream_url", sa.String(500)),
            sa.Column("stream_protocol", sa.String(20), server_default=sa.text("'rtsp'")),
            sa.Column("ai_enabled", sa.Boolean(), server_default=sa.text("false")),
            sa.Column("ai_capabilities", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
            sa.Column("platform_device_id", sa.String(100)),
            sa.Column("online_status", sa.String(20), server_default=sa.text("'offline'")),
            sa.Column("last_heartbeat", sa.TIMESTAMP(timezone=True)),
            sa.Column("installed_at", sa.TIMESTAMP(timezone=True)),
            sa.Column("location_desc", sa.String(200)),
            sa.Column("tenant_id", postgresql.UUID(), nullable=False),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
        )
        op.create_index("ix_kd_tenant_store", "kitchen_devices", ["tenant_id", "store_id"])
        _add_rls("kitchen_devices", "kd")

        # --- kitchen_ai_alerts AI告警记录 ---

    if 'kitchen_ai_alerts' not in existing:
        op.create_table(
            "kitchen_ai_alerts",
            sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
            sa.Column("store_id", postgresql.UUID(), nullable=False),
            sa.Column("device_id", postgresql.UUID(), nullable=False),
            sa.Column("alert_type", sa.String(50), nullable=False),
            sa.Column("severity", sa.String(20), server_default=sa.text("'warning'")),
            sa.Column("snapshot_url", sa.String(500)),
            sa.Column("video_clip_url", sa.String(500)),
            sa.Column("confidence_score", sa.Numeric(5, 4)),
            sa.Column("auto_submitted", sa.Boolean(), server_default=sa.text("false")),
            sa.Column("submission_id", postgresql.UUID()),
            sa.Column("resolved_at", sa.TIMESTAMP(timezone=True)),
            sa.Column("resolved_by", postgresql.UUID()),
            sa.Column("resolution_notes", sa.Text()),
            sa.Column("false_positive", sa.Boolean(), server_default=sa.text("false")),
            sa.Column("alert_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("tenant_id", postgresql.UUID(), nullable=False),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
        )
        op.create_index("ix_kai_tenant_store", "kitchen_ai_alerts", ["tenant_id", "store_id"])
        op.create_index("ix_kai_type", "kitchen_ai_alerts", ["tenant_id", "alert_type"])
        op.execute("""
            CREATE INDEX ix_kai_unresolved ON kitchen_ai_alerts (tenant_id, store_id)
            WHERE resolved_at IS NULL
        """)
        _add_rls("kitchen_ai_alerts", "kai")

        # --- env_emission_records 油烟排放记录 ---

    if 'env_emission_records' not in existing:
        op.create_table(
            "env_emission_records",
            sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
            sa.Column("store_id", postgresql.UUID(), nullable=False),
            sa.Column("device_id", sa.String(100)),
            sa.Column("pm25", sa.Numeric(8, 2)),
            sa.Column("pm10", sa.Numeric(8, 2)),
            sa.Column("nmhc", sa.Numeric(8, 2)),
            sa.Column("emission_concentration", sa.Numeric(8, 2)),
            sa.Column("purifier_efficiency", sa.Numeric(5, 2)),
            sa.Column("is_compliant", sa.Boolean(), server_default=sa.text("true")),
            sa.Column("recorded_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("submitted_at", sa.TIMESTAMP(timezone=True)),
            sa.Column("submission_id", postgresql.UUID()),
            sa.Column("tenant_id", postgresql.UUID(), nullable=False),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
        )
        op.create_index("ix_eer_tenant_store", "env_emission_records", ["tenant_id", "store_id"])
        op.create_index("ix_eer_date", "env_emission_records", ["tenant_id", "store_id", "recorded_at"])
        _add_rls("env_emission_records", "eer")

        # --- env_waste_disposal 餐厨垃圾台账 ---

    if 'env_waste_disposal' not in existing:
        op.create_table(
            "env_waste_disposal",
            sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
            sa.Column("store_id", postgresql.UUID(), nullable=False),
            sa.Column("waste_type", sa.String(30), nullable=False),
            sa.Column("weight_kg", sa.Numeric(10, 2), nullable=False),
            sa.Column("collector_company", sa.String(200)),
            sa.Column("collector_license", sa.String(100)),
            sa.Column("vehicle_plate", sa.String(20)),
            sa.Column("disposal_cert_no", sa.String(100)),
            sa.Column("collected_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("photos", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
            sa.Column("notes", sa.Text()),
            sa.Column("submitted_at", sa.TIMESTAMP(timezone=True)),
            sa.Column("submission_id", postgresql.UUID()),
            sa.Column("tenant_id", postgresql.UUID(), nullable=False),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
        )
        op.create_index("ix_ewd_tenant_store", "env_waste_disposal", ["tenant_id", "store_id"])
        op.create_index("ix_ewd_date", "env_waste_disposal", ["tenant_id", "store_id", "collected_at"])
        _add_rls("env_waste_disposal", "ewd")



def downgrade() -> None:
    op.drop_table("env_waste_disposal")
    op.drop_table("env_emission_records")
    op.drop_table("kitchen_ai_alerts")
    op.drop_table("kitchen_devices")
