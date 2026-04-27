"""v143 — 高峰值守表: peak_events + store_peak_configs

新增两张表：
  peak_events         — E3 高峰事件记录（临时调菜/调台/分流等操作日志）
  store_peak_configs  — E3 门店高峰期配置（午高峰/晚高峰时段+人员配置）

每张表均含 tenant_id + NULLIF RLS 策略（防 NULL 绕过）+ FORCE。

Revision ID: v143
Revises: v142
Create Date: 2026-04-04
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "v143"
down_revision = "v142"
branch_labels = None
depends_on = None

_SAFE_RLS = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    _bind = op.get_bind()
    _inspector = sa.inspect(_bind)
    _existing = set(_inspector.get_table_names())

    # ── peak_events 高峰事件记录 ─────────────────────────────────────────
    if "peak_events" not in _existing:
        op.create_table(
            "peak_events",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("event_type", sa.String(50), nullable=False),
            sa.Column("params", sa.Text, nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='peak_events' AND column_name IN ('tenant_id', 'store_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_peak_events_tenant_store ON peak_events (tenant_id, store_id)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='peak_events' AND column_name IN ('tenant_id', 'event_type')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_peak_events_tenant_type ON peak_events (tenant_id, event_type)';
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='peak_events' AND column_name IN ('tenant_id', 'status')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_peak_events_tenant_status ON peak_events (tenant_id, status)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE peak_events ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE peak_events FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY peak_events_rls ON peak_events
        USING ({_SAFE_RLS})
        WITH CHECK ({_SAFE_RLS});
    """)

    # ── store_peak_configs 门店高峰期配置 ────────────────────────────────
    if "store_peak_configs" not in _existing:
        op.create_table(
            "store_peak_configs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("peak_name", sa.String(50), nullable=True),
            sa.Column("start_time", sa.Time, nullable=False),
            sa.Column("end_time", sa.Time, nullable=False),
            sa.Column("expected_covers", sa.Integer, nullable=True),
            sa.Column("staff_required", sa.Integer, nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
    op.execute("""
        DO $$ BEGIN
            IF (SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='store_peak_configs' AND column_name IN ('tenant_id', 'store_id')) = 2 THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_store_peak_configs_tenant_store ON store_peak_configs (tenant_id, store_id)';
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE store_peak_configs ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE store_peak_configs FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY store_peak_configs_rls ON store_peak_configs
        USING ({_SAFE_RLS})
        WITH CHECK ({_SAFE_RLS});
    """)


def downgrade() -> None:
    for table in ["store_peak_configs", "peak_events"]:
        op.execute(f"DROP POLICY IF EXISTS {table}_rls ON {table};")
        op.drop_table(table)
