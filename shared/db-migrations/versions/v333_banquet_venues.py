"""v317 — 宴会场地模块: banquet_venues / banquet_venue_bookings

宴会厅/场地管理与档期预订。支持6种场地类型、7种时段、
档期占位（held）→确认→释放流程，含部分唯一约束防止双重预订。

Revision ID: v317_banquet_venues
Revises: v316_banquet_quotes
Create Date: 2026-04-25
"""
from alembic import op

revision = "v333_banquet_venues"
down_revision = "v332_banquet_quotes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── banquet_venues 宴会厅/场地 ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_venues (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            store_id                UUID NOT NULL,
            venue_name              VARCHAR(100) NOT NULL,
            venue_type              VARCHAR(30) NOT NULL
                CHECK (venue_type IN ('grand_hall','medium_hall','private_room','outdoor','rooftop','multi_function')),
            floor                   INT DEFAULT 1,
            area_sqm                NUMERIC(8,2),
            max_tables              INT NOT NULL,
            max_guests              INT NOT NULL,
            min_tables              INT DEFAULT 1,
            base_fee_fen            INT DEFAULT 0,
            decoration_options_json JSONB DEFAULT '[]'::jsonb,
            facilities_json         JSONB DEFAULT '[]'::jsonb,
            photos_json             JSONB DEFAULT '[]'::jsonb,
            rules_json              JSONB DEFAULT '{}'::jsonb,
            is_active               BOOLEAN DEFAULT TRUE,
            sort_order              INT DEFAULT 0,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_bv_tenant_store
            ON banquet_venues(tenant_id, store_id)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_bv_type
            ON banquet_venues(tenant_id, venue_type)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE banquet_venues ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS banquet_venues_tenant_isolation ON banquet_venues;
        CREATE POLICY banquet_venues_tenant_isolation ON banquet_venues
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE banquet_venues FORCE ROW LEVEL SECURITY")

    # ── banquet_venue_bookings 厅房档期 ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS banquet_venue_bookings (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     UUID NOT NULL,
            venue_id      UUID NOT NULL REFERENCES banquet_venues(id),
            banquet_id    UUID,
            lead_id       UUID REFERENCES banquet_leads(id),
            booking_date  DATE NOT NULL,
            time_slot     VARCHAR(20) NOT NULL
                CHECK (time_slot IN ('breakfast','lunch','dinner','full_day','morning','afternoon','evening')),
            status        VARCHAR(20) DEFAULT 'held'
                CHECK (status IN ('held','confirmed','released','completed','cancelled')),
            held_until    TIMESTAMPTZ,
            confirmed_at  TIMESTAMPTZ,
            released_at   TIMESTAMPTZ,
            notes         VARCHAR(500),
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted    BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    # Partial unique index: prevent double-booking for active bookings
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_bvb_venue_date_slot
            ON banquet_venue_bookings(tenant_id, venue_id, booking_date, time_slot)
            WHERE is_deleted = false AND status NOT IN ('released','cancelled')
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_bvb_venue_date
            ON banquet_venue_bookings(tenant_id, venue_id, booking_date)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_bvb_date
            ON banquet_venue_bookings(tenant_id, booking_date)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_bvb_status
            ON banquet_venue_bookings(tenant_id, status)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE banquet_venue_bookings ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS banquet_venue_bookings_tenant_isolation ON banquet_venue_bookings;
        CREATE POLICY banquet_venue_bookings_tenant_isolation ON banquet_venue_bookings
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)
    op.execute("ALTER TABLE banquet_venue_bookings FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS banquet_venue_bookings CASCADE")
    op.execute("DROP TABLE IF EXISTS banquet_venues CASCADE")
