"""v054: 经营诊断报告表 — business_diagnosis_reports

新增表：
  business_diagnosis_reports — 每日经营诊断报告（异常列表 + AI 摘要 + 原始数据）

RLS 策略：
  标准安全模式（4操作 + NULL guard + FORCE ROW LEVEL SECURITY）
  NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID

Revision ID: v054
Revises: v047
Create Date: 2026-03-31
"""

from alembic import op

revision = "v054"
down_revision = "v047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # business_diagnosis_reports
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS business_diagnosis_reports (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            store_id        UUID        NOT NULL,
            report_date     DATE        NOT NULL,
            anomalies       JSONB       NOT NULL DEFAULT '[]',
            summary_text    TEXT        NOT NULL DEFAULT '',
            raw_data        JSONB       NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT uq_diagnosis_report_store_date
                UNIQUE (tenant_id, store_id, report_date)
        );

        COMMENT ON TABLE business_diagnosis_reports IS
            '经营诊断报告：每日门店经营异常检测结果，包含异常列表、AI摘要和原始数据';

        COMMENT ON COLUMN business_diagnosis_reports.anomalies IS
            'JSONB数组：[{rule_id, rule_name, severity, description, actual_value, threshold_value, context}]';
        COMMENT ON COLUMN business_diagnosis_reports.summary_text IS
            'Claude API生成的三段式自然语言诊断摘要（总结/问题/建议）';
        COMMENT ON COLUMN business_diagnosis_reports.raw_data IS
            '原始数据快照：从tx-analytics拉取的日汇总数据，便于事后审计';

        CREATE INDEX IF NOT EXISTS ix_diagnosis_reports_tenant_store_date
            ON business_diagnosis_reports (tenant_id, store_id, report_date DESC);

        CREATE INDEX IF NOT EXISTS ix_diagnosis_reports_tenant_date
            ON business_diagnosis_reports (tenant_id, report_date DESC);

        CREATE INDEX IF NOT EXISTS ix_diagnosis_reports_anomalies_gin
            ON business_diagnosis_reports USING GIN (anomalies);
    """)

    # RLS: business_diagnosis_reports
    op.execute("""
        ALTER TABLE business_diagnosis_reports ENABLE ROW LEVEL SECURITY;
        ALTER TABLE business_diagnosis_reports FORCE ROW LEVEL SECURITY;

        CREATE POLICY business_diagnosis_reports_tenant_isolation
            ON business_diagnosis_reports
            AS PERMISSIVE FOR ALL
            USING (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            )
            WITH CHECK (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
    """)


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS business_diagnosis_reports_tenant_isolation "
        "ON business_diagnosis_reports;"
    )
    op.execute("DROP TABLE IF EXISTS business_diagnosis_reports;")
