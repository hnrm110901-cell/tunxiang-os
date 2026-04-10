"""v100: 小红书平台对接 — POI 映射 + 团购券核销记录

新建 2 张表：
  - xhs_poi_mappings          — 门店与小红书 POI 的绑定关系
  - xhs_coupon_verifications   — 团购券核销记录（含券码/金额/门店/对账状态）

设计要点：
  - xhs_poi_mappings 用 (tenant_id, store_id) UNIQUE 保证一店一 POI
  - xhs_coupon_verifications 用 coupon_code UNIQUE 防止重复核销
  - 对账状态：verified → reconciled（每日批量对账后标记）

Revision ID: v100
Revises: v099
Create Date: 2026-04-01
"""

from alembic import op

revision = "v100b"
down_revision = "v100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. xhs_poi_mappings — 门店 ↔ 小红书 POI 绑定 ─────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS xhs_poi_mappings (
            id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID         NOT NULL,
            store_id        UUID         NOT NULL,
            xhs_poi_id      VARCHAR(64)  NOT NULL,
            xhs_shop_name   VARCHAR(200),
            sync_status     VARCHAR(20)  NOT NULL DEFAULT 'pending',
            last_synced_at  TIMESTAMPTZ,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN      NOT NULL DEFAULT FALSE,
            UNIQUE (tenant_id, store_id)
        )
    """)
    op.execute("ALTER TABLE xhs_poi_mappings ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY xhs_poi_mappings_rls ON xhs_poi_mappings
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    # Ensure is_deleted column exists (table may predate this migration)
    op.execute("""
        ALTER TABLE xhs_poi_mappings
            ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_xhs_poi_tenant_store
            ON xhs_poi_mappings(tenant_id, store_id)
            WHERE is_deleted = false
    """)

    # ── 2. xhs_coupon_verifications — 团购券核销记录 ──────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS xhs_coupon_verifications (
            id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID         NOT NULL,
            store_id        UUID         NOT NULL,
            order_id        UUID,
            coupon_code     VARCHAR(128) NOT NULL UNIQUE,
            coupon_type     VARCHAR(30)  NOT NULL DEFAULT 'group_buy',
            original_fen    INT          NOT NULL DEFAULT 0,
            paid_fen        INT          NOT NULL DEFAULT 0,
            platform_fee_fen INT         NOT NULL DEFAULT 0,
            settle_fen      INT          NOT NULL DEFAULT 0,
            status          VARCHAR(20)  NOT NULL DEFAULT 'verified',
            xhs_order_id    VARCHAR(64),
            xhs_verify_time TIMESTAMPTZ,
            reconciled_at   TIMESTAMPTZ,
            verified_by     UUID,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN      NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("ALTER TABLE xhs_coupon_verifications ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY xhs_coupon_verifications_rls ON xhs_coupon_verifications
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_xhs_coupon_tenant_store
            ON xhs_coupon_verifications(tenant_id, store_id, status)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_xhs_coupon_code
            ON xhs_coupon_verifications(coupon_code)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS xhs_coupon_verifications CASCADE")
    op.execute("DROP TABLE IF EXISTS xhs_poi_mappings CASCADE")
