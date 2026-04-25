"""v325 — 跨品牌联盟合作伙伴表: alliance_partners

跨品牌联盟忠诚度 S4W13-14：
  联盟合作伙伴管理，支持餐饮/零售/娱乐/健身/酒店等异业合作，
  积分互通兑换，合同管理，每日兑换额度限制。

Revision ID: v325_alliance_partners
Revises: v324_content_calendar
Create Date: 2026-04-25
"""
from alembic import op

revision = "v325_alliance_partners"
down_revision = "v324_content_calendar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS alliance_partners (
            id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id                   UUID NOT NULL,
            partner_name                VARCHAR(200) NOT NULL,
            partner_type                VARCHAR(30) NOT NULL
                                        CHECK (partner_type IN (
                                            'restaurant', 'retail', 'entertainment',
                                            'fitness', 'hotel', 'other'
                                        )),
            partner_brand_logo          VARCHAR(500),
            contact_name                VARCHAR(100),
            contact_phone               VARCHAR(30),
            contact_email               VARCHAR(200),
            api_endpoint                VARCHAR(500),
            api_key_encrypted           TEXT,
            exchange_rate_out           FLOAT NOT NULL DEFAULT 1.0,
            exchange_rate_in            FLOAT NOT NULL DEFAULT 1.0,
            daily_exchange_limit        INT NOT NULL DEFAULT 1000,
            status                      VARCHAR(20) NOT NULL DEFAULT 'pending'
                                        CHECK (status IN (
                                            'pending', 'active', 'suspended', 'terminated'
                                        )),
            contract_start              DATE,
            contract_end                DATE,
            terms_summary               TEXT,
            total_points_exchanged_out  BIGINT NOT NULL DEFAULT 0,
            total_points_exchanged_in   BIGINT NOT NULL DEFAULT 0,
            created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted                  BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_alliance_partners_status
            ON alliance_partners(tenant_id, status)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_alliance_partners_type
            ON alliance_partners(tenant_id, partner_type)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE alliance_partners ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS alliance_partners_tenant_isolation ON alliance_partners;
        CREATE POLICY alliance_partners_tenant_isolation ON alliance_partners
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE alliance_partners FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS alliance_partners CASCADE")
