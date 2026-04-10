"""v176 — 巡店质检报告（E8）

创建：
  inspection_reports — 巡店报告主表（draft/submitted/acknowledged/closed 流转）

字段说明：
  dimensions  — JSONB，各维度评分 [{name, score, max_score, issues:[]}]
  photos      — JSONB，现场照片 [{url, caption, issue_id}]
  action_items — JSONB，整改事项 [{item, deadline, owner}]
  overall_score — 综合得分（0-100），由 dimensions 计算而来

Revision: v176
"""

from alembic import op

revision = "v176"
down_revision = "v175"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS inspection_reports (
            id               UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id        UUID        NOT NULL,
            store_id         UUID        NOT NULL,
            inspection_date  DATE        NOT NULL,
            inspector_id     UUID        NOT NULL,
            overall_score    NUMERIC(5,1),
            -- 综合得分 0-100.0，NULL 表示无评分维度
            dimensions       JSONB       NOT NULL DEFAULT '[]',
            -- [{name, score, max_score, issues:[]}]
            photos           JSONB       NOT NULL DEFAULT '[]',
            -- [{url, caption, issue_id}]
            action_items     JSONB       NOT NULL DEFAULT '[]',
            -- [{item, deadline, owner}]
            notes            TEXT,
            ack_notes        TEXT,
            status           VARCHAR(16) NOT NULL DEFAULT 'draft',
            -- draft / submitted / acknowledged / closed
            acknowledged_by  UUID,
            acknowledged_at  TIMESTAMPTZ,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted       BOOLEAN     NOT NULL DEFAULT FALSE
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_inspection_reports_tenant_store "
        "ON inspection_reports (tenant_id, store_id, inspection_date DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_inspection_reports_tenant_date "
        "ON inspection_reports (tenant_id, inspection_date DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_inspection_reports_inspector "
        "ON inspection_reports (tenant_id, inspector_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_inspection_reports_status "
        "ON inspection_reports (tenant_id, status) WHERE is_deleted = FALSE"
    )
    op.execute("ALTER TABLE inspection_reports ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY inspection_reports_rls ON inspection_reports
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)
    op.execute("ALTER TABLE inspection_reports FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS inspection_reports")
