"""v181 — 合规预警表（compliance_alerts）

创建：
  compliance_alerts — 合规预警主表（健康证过期/合同到期/食安违规等）

字段说明：
  alert_type  — 预警类型（health_cert_expiry / contract_expiry / food_safety 等）
  severity    — 严重级别（info / warning / critical）
  status      — 状态（open / acknowledged / resolved / dismissed）
  source      — 来源（system / manual / agent）

Revision: v181
"""

from alembic import op

revision = "v181"
down_revision = "v180"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS compliance_alerts (
            id              UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id       UUID        NOT NULL,
            store_id        UUID,
            employee_id     UUID,
            alert_type      TEXT        NOT NULL,
            severity        TEXT        NOT NULL,
            title           TEXT        NOT NULL,
            detail          JSONB,
            status          TEXT        DEFAULT 'open',
            resolved_by     UUID,
            resolved_at     TIMESTAMPTZ,
            resolution_note TEXT,
            due_date        DATE,
            source          TEXT        DEFAULT 'system',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_compliance_alerts_tenant_status ON compliance_alerts (tenant_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_compliance_alerts_tenant_type ON compliance_alerts (tenant_id, alert_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_compliance_alerts_tenant_store_status "
        "ON compliance_alerts (tenant_id, store_id, status)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_compliance_alerts_severity ON compliance_alerts (severity)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_compliance_alerts_due_date ON compliance_alerts (due_date)")
    op.execute("ALTER TABLE compliance_alerts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE compliance_alerts FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS compliance_alerts_tenant_isolation ON compliance_alerts")
    op.execute("""
        CREATE POLICY compliance_alerts_tenant_isolation ON compliance_alerts
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS compliance_alerts")
