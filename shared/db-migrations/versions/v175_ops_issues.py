"""v175 — 问题预警与整改跟踪（E5/E6）

创建：
  ops_issues — 问题记录主表（预警、指派、整改、关闭全生命周期）

Revision: v175
"""

from alembic import op

revision = "v175"
down_revision = "v174"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS ops_issues (
            id               UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id        UUID        NOT NULL,
            store_id         UUID        NOT NULL,
            issue_date       DATE        NOT NULL,
            issue_type       VARCHAR(32) NOT NULL,
            -- discount_abuse / food_safety / device_fault / service / kds_timeout
            severity         VARCHAR(16) NOT NULL DEFAULT 'medium',
            -- critical / high / medium / low
            title            VARCHAR(200) NOT NULL,
            description      TEXT,
            evidence_urls    JSONB       NOT NULL DEFAULT '[]',
            assigned_to      UUID,
            due_at           TIMESTAMPTZ NOT NULL,
            resolved_at      TIMESTAMPTZ,
            resolution_notes TEXT,
            resolved_by      UUID,
            status           VARCHAR(16) NOT NULL DEFAULT 'open',
            -- open / in_progress / resolved / closed / escalated
            created_by       VARCHAR(100),
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted       BOOLEAN     NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_ops_issues_tenant_store ON ops_issues (tenant_id, store_id, issue_date DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ops_issues_tenant_status ON ops_issues (tenant_id, status) WHERE is_deleted = FALSE")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ops_issues_tenant_severity ON ops_issues (tenant_id, severity) WHERE is_deleted = FALSE")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ops_issues_tenant_type ON ops_issues (tenant_id, issue_type) WHERE is_deleted = FALSE")
    op.execute("ALTER TABLE ops_issues ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY ops_issues_rls ON ops_issues
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)
    op.execute("ALTER TABLE ops_issues FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ops_issues")
