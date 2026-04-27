"""v315 — 宴会线索模块: banquet_leads / banquet_lead_follow_ups / banquet_lead_transfers

宴会CRM第一步：线索录入、销售跟进、客资转移。
支持8种宴席类型、6种来源渠道、6种线索状态。

Revision ID: v315_banquet_leads
Revises: v325_surprise_rules (reanchored from missing v330_reputation_alerts)
Create Date: 2026-04-25
"""
from alembic import op

revision = "v331_banquet_leads"
down_revision = "v325_surprise_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── banquet_leads 宴会线索 ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_leads (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id            UUID NOT NULL,
            lead_no              VARCHAR(20) NOT NULL UNIQUE,
            store_id             UUID NOT NULL,
            customer_name        VARCHAR(100) NOT NULL,
            phone                VARCHAR(20) NOT NULL,
            company              VARCHAR(200),
            event_type           VARCHAR(30) NOT NULL
                CHECK (event_type IN ('wedding','birthday','business','tour_group','conference','annual_party','memorial','other')),
            event_date           DATE,
            guest_count_est      INT,
            table_count_est      INT,
            budget_per_table_fen INT DEFAULT 0,
            source_channel       VARCHAR(30) DEFAULT 'walk_in'
                CHECK (source_channel IN ('walk_in','phone','wechat','meituan','douyin','referral','website','other')),
            assigned_sales_id    UUID,
            status               VARCHAR(20) DEFAULT 'new'
                CHECK (status IN ('new','following','quoted','contracted','won','lost')),
            priority             VARCHAR(10) DEFAULT 'normal'
                CHECK (priority IN ('low','normal','high','urgent')),
            follow_up_at         TIMESTAMPTZ,
            lost_reason          VARCHAR(500),
            referral_lead_id     UUID REFERENCES banquet_leads(id),
            notes                TEXT,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted           BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_bl_tenant_store
            ON banquet_leads(tenant_id, store_id)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_bl_status
            ON banquet_leads(tenant_id, status)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_bl_phone
            ON banquet_leads(tenant_id, phone)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_bl_event_date
            ON banquet_leads(tenant_id, event_date)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE banquet_leads ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS banquet_leads_tenant_isolation ON banquet_leads;
        CREATE POLICY banquet_leads_tenant_isolation ON banquet_leads
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE banquet_leads FORCE ROW LEVEL SECURITY")

    # ── banquet_lead_follow_ups 跟进记录 ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_lead_follow_ups (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            lead_id         UUID NOT NULL REFERENCES banquet_leads(id),
            sales_id        UUID NOT NULL,
            follow_type     VARCHAR(20) NOT NULL
                CHECK (follow_type IN ('phone','visit','wechat','demo','email','other')),
            content         TEXT NOT NULL,
            next_action     VARCHAR(500),
            next_follow_at  TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_blf_lead
            ON banquet_lead_follow_ups(tenant_id, lead_id)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE banquet_lead_follow_ups ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS banquet_lead_follow_ups_tenant_isolation ON banquet_lead_follow_ups;
        CREATE POLICY banquet_lead_follow_ups_tenant_isolation ON banquet_lead_follow_ups
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE banquet_lead_follow_ups FORCE ROW LEVEL SECURITY")

    # ── banquet_lead_transfers 客资转移 ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_lead_transfers (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID NOT NULL,
            lead_id          UUID NOT NULL REFERENCES banquet_leads(id),
            from_employee_id UUID NOT NULL,
            to_employee_id   UUID NOT NULL,
            reason           VARCHAR(500),
            transferred_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted       BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_blt_lead
            ON banquet_lead_transfers(tenant_id, lead_id)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE banquet_lead_transfers ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS banquet_lead_transfers_tenant_isolation ON banquet_lead_transfers;
        CREATE POLICY banquet_lead_transfers_tenant_isolation ON banquet_lead_transfers
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE banquet_lead_transfers FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS banquet_lead_transfers CASCADE")
    op.execute("DROP TABLE IF EXISTS banquet_lead_follow_ups CASCADE")
    op.execute("DROP TABLE IF EXISTS banquet_leads CASCADE")
