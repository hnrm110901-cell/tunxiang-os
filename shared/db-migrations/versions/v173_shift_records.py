"""v173 — 班次交班记录（E1）

创建：
  shift_records          — 班次主记录（开班/交班状态）
  shift_device_checklist — 设备检查明细（每班次 N 条）

Revision: v173
"""

from alembic import op

revision = "v173"
down_revision = "v172"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS shift_records (
            id              UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id       UUID        NOT NULL,
            store_id        UUID        NOT NULL,
            shift_date      DATE        NOT NULL,
            shift_type      VARCHAR(16) NOT NULL,
            -- morning / afternoon / evening / night
            start_time      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            end_time        TIMESTAMPTZ,
            handover_by     UUID        NOT NULL,
            received_by     UUID,
            cash_counted_fen BIGINT     NOT NULL DEFAULT 0,
            pos_cash_fen    BIGINT      NOT NULL DEFAULT 0,
            cash_diff_fen   BIGINT      NOT NULL DEFAULT 0,
            notes           TEXT,
            status          VARCHAR(16) NOT NULL DEFAULT 'pending',
            -- pending / confirmed / disputed
            disputed        BOOLEAN     NOT NULL DEFAULT FALSE,
            dispute_reason  TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN     NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_shift_records_tenant_store ON shift_records (tenant_id, store_id, shift_date DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_shift_records_tenant_date ON shift_records (tenant_id, shift_date DESC)")
    op.execute("ALTER TABLE shift_records ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY shift_records_rls ON shift_records
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)
    op.execute("ALTER TABLE shift_records FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE TABLE IF NOT EXISTS shift_device_checklist (
            id          UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            shift_id    UUID        NOT NULL REFERENCES shift_records(id) ON DELETE CASCADE,
            tenant_id   UUID        NOT NULL,
            item        VARCHAR(64) NOT NULL,
            status      VARCHAR(16) NOT NULL DEFAULT 'ok',
            -- ok / warning / failed
            note        TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_shift_device_checklist_shift ON shift_device_checklist (shift_id)")
    op.execute("ALTER TABLE shift_device_checklist ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY shift_device_checklist_rls ON shift_device_checklist
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)
    op.execute("ALTER TABLE shift_device_checklist FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS shift_device_checklist")
    op.execute("DROP TABLE IF EXISTS shift_records")
