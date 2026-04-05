"""v103: 零售商城 DB — 激活 retail_mall.py 已引用的表

新建 4 张表：
  - retail_products     — 商品表（名称/分类/价格/图片/库存/排序）
  - retail_orders       — 零售订单（用户/地址/金额/支付/物流/状态）
  - retail_order_items  — 订单商品行项
  - retail_cart_items   — 购物车

设计要点：
  - retail_products 的 SQL 列名与 retail_mall.py 中已有查询完全对齐
  - 库存扣减通过 UPDATE stock = stock - :qty WHERE stock >= :qty 原子操作
  - 购物车为临时状态，不参与财务对账

Revision ID: v103
Revises: v102
Create Date: 2026-04-01
"""

from alembic import op

revision = "v103b"
down_revision = "v103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. retail_products — 商品表 ──────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS retail_products (
            id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID         NOT NULL,
            name                VARCHAR(200) NOT NULL,
            category            VARCHAR(30)  NOT NULL,
            cover_image         TEXT,
            images              JSONB        NOT NULL DEFAULT '[]',
            description         TEXT,
            price_fen           INT          NOT NULL,
            original_price_fen  INT,
            cost_fen            INT          NOT NULL DEFAULT 0,
            stock               INT          NOT NULL DEFAULT 0,
            sales_count         INT          NOT NULL DEFAULT 0,
            rating              NUMERIC(3,2) NOT NULL DEFAULT 5.00,
            tags                JSONB        NOT NULL DEFAULT '[]',
            skus                JSONB        NOT NULL DEFAULT '[]',
            sort_order          INT          NOT NULL DEFAULT 0,
            status              VARCHAR(20)  NOT NULL DEFAULT 'draft',
            origin              VARCHAR(100),
            shelf_life          VARCHAR(50),
            specs               JSONB        NOT NULL DEFAULT '{}',
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN      NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("ALTER TABLE retail_products ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY retail_products_rls ON retail_products
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    # Ensure is_deleted column exists (table may predate this migration)
    op.execute("""
        ALTER TABLE retail_products
            ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE
    """)
    # Ensure is_deleted column exists (table may predate this migration)
    op.execute("""
        ALTER TABLE retail_orders
            ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_retail_products_tenant_cat
            ON retail_products(tenant_id, category, status)
            WHERE is_deleted = false
    """)

    # ── 2. retail_orders — 零售订单 ──────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS retail_orders (
            id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID         NOT NULL,
            order_no          VARCHAR(32)  NOT NULL UNIQUE,
            customer_id       UUID         NOT NULL,
            total_fen         INT          NOT NULL DEFAULT 0,
            discount_fen      INT          NOT NULL DEFAULT 0,
            delivery_fee_fen  INT          NOT NULL DEFAULT 0,
            actual_fen        INT          NOT NULL DEFAULT 0,
            status            VARCHAR(20)  NOT NULL DEFAULT 'pending',
            address           JSONB        NOT NULL DEFAULT '{}',
            payment_method    VARCHAR(30),
            paid_at           TIMESTAMPTZ,
            express_company   VARCHAR(50),
            tracking_no       VARCHAR(64),
            shipped_at        TIMESTAMPTZ,
            delivered_at      TIMESTAMPTZ,
            completed_at      TIMESTAMPTZ,
            cancelled_at      TIMESTAMPTZ,
            cancel_reason     TEXT,
            refund_fen        INT          NOT NULL DEFAULT 0,
            refunded_at       TIMESTAMPTZ,
            created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted        BOOLEAN      NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("ALTER TABLE retail_orders ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY retail_orders_rls ON retail_orders
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_retail_orders_tenant_customer
            ON retail_orders(tenant_id, customer_id, status)
            WHERE is_deleted = false
    """)

    # ── 3. retail_order_items — 订单商品行项 ─────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS retail_order_items (
            id            UUID   PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     UUID   NOT NULL,
            order_id      UUID   NOT NULL REFERENCES retail_orders(id),
            product_id    UUID   NOT NULL,
            sku_id        VARCHAR(64) NOT NULL,
            product_name  VARCHAR(200),
            quantity      INT    NOT NULL DEFAULT 1,
            unit_price_fen INT   NOT NULL DEFAULT 0,
            total_fen     INT    NOT NULL DEFAULT 0,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted    BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("ALTER TABLE retail_order_items ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY retail_order_items_rls ON retail_order_items
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)

    # ── 4. retail_cart_items — 购物车 ────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS retail_cart_items (
            id            UUID   PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     UUID   NOT NULL,
            customer_id   UUID   NOT NULL,
            product_id    UUID   NOT NULL,
            sku_id        VARCHAR(64) NOT NULL,
            quantity      INT    NOT NULL DEFAULT 1,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted    BOOLEAN NOT NULL DEFAULT FALSE,
            UNIQUE (tenant_id, customer_id, product_id, sku_id)
        )
    """)
    op.execute("ALTER TABLE retail_cart_items ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY retail_cart_items_rls ON retail_cart_items
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS retail_cart_items CASCADE")
    op.execute("DROP TABLE IF EXISTS retail_order_items CASCADE")
    op.execute("DROP TABLE IF EXISTS retail_orders CASCADE")
    op.execute("DROP TABLE IF EXISTS retail_products CASCADE")
