"""外卖平台聚合 — 订单/商品/费率管理

新增表：
  delivery_platform_configs  — 美团/饿了么/抖音平台接入配置（含密钥/费率）
  delivery_orders            — 外卖平台订单（统一格式存储 + 原始 payload）
  delivery_platform_items    — 外卖平台商品映射（内部 dish ↔ 平台 SKU）

RLS 策略：
  全部使用 v006+ 标准安全模式（4操作 + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v058
Revises: v047
Create Date: 2026-03-31
"""

from alembic import op

revision = "v058"
down_revision = "v047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 1. delivery_platform_configs — 外卖平台接入配置
    #    每个门店每个平台一条记录，存储 AppID/密钥/店铺ID/佣金费率
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS delivery_platform_configs (
            id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID        NOT NULL,
            store_id         UUID        NOT NULL,
            platform         VARCHAR(20) NOT NULL
                CHECK (platform IN ('meituan', 'eleme', 'douyin')),
            app_id           VARCHAR(100) NOT NULL,
            app_secret       TEXT        NOT NULL,          -- 加密存储（AES-256）
            shop_id          VARCHAR(100) NOT NULL,
            is_active        BOOLEAN     NOT NULL DEFAULT TRUE,
            commission_rate  NUMERIC(5,4) NOT NULL DEFAULT 0.18,  -- 默认18%
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted       BOOLEAN     NOT NULL DEFAULT FALSE,

            CONSTRAINT uq_delivery_platform_configs_store_platform
                UNIQUE (tenant_id, store_id, platform)
        );

        COMMENT ON TABLE delivery_platform_configs IS
            '外卖平台接入配置：每个门店每个平台的 AppID/密钥/店铺ID/佣金费率';
        COMMENT ON COLUMN delivery_platform_configs.app_secret IS
            'AES-256 加密存储，明文仅在内存中短暂存在';
        COMMENT ON COLUMN delivery_platform_configs.commission_rate IS
            '平台佣金费率，如 0.18 表示 18%';

        CREATE INDEX IF NOT EXISTS ix_delivery_platform_configs_store
            ON delivery_platform_configs (tenant_id, store_id)
            WHERE is_deleted = FALSE AND is_active = TRUE;
    """)

    # RLS: delivery_platform_configs
    op.execute("""
        ALTER TABLE delivery_platform_configs ENABLE ROW LEVEL SECURITY;
        ALTER TABLE delivery_platform_configs FORCE ROW LEVEL SECURITY;

        CREATE POLICY delivery_platform_configs_tenant_isolation
            ON delivery_platform_configs
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

    # ─────────────────────────────────────────────────────────────────
    # 2. delivery_orders — 外卖平台订单（统一格式）
    #    所有平台的外卖订单统一写入此表，同时保留原始 payload 用于对账
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS delivery_orders (
            id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id            UUID        NOT NULL,
            store_id             UUID        NOT NULL,
            platform             VARCHAR(20) NOT NULL
                CHECK (platform IN ('meituan', 'eleme', 'douyin')),
            platform_order_id    VARCHAR(100) NOT NULL,
            status               VARCHAR(30) NOT NULL DEFAULT 'pending'
                CHECK (status IN (
                    'pending',      -- 待确认
                    'confirmed',    -- 已接单
                    'preparing',    -- 制作中
                    'ready',        -- 出餐完成
                    'dispatched',   -- 骑手已取
                    'delivered',    -- 已送达
                    'cancelled',    -- 已取消
                    'rejected'      -- 已拒单
                )),
            -- 订单内容
            items                JSONB       NOT NULL DEFAULT '[]',
            total_fen            INT         NOT NULL DEFAULT 0,   -- 总金额（分）
            delivery_fee_fen     INT         NOT NULL DEFAULT 0,   -- 配送费（分）
            commission_fen       INT         NOT NULL DEFAULT 0,   -- 平台佣金（分）
            -- 客户信息
            customer_name        VARCHAR(50),
            customer_phone       VARCHAR(20),
            delivery_address     TEXT,
            -- 时间节点
            estimated_delivery_at TIMESTAMPTZ,
            actual_delivery_at   TIMESTAMPTZ,
            -- 关联内部订单
            internal_order_id    UUID,
            -- 原始数据
            raw_payload          JSONB       NOT NULL DEFAULT '{}',
            -- 拒单原因
            reject_reason        TEXT,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted           BOOLEAN     NOT NULL DEFAULT FALSE,

            CONSTRAINT uq_delivery_orders_platform_order
                UNIQUE (tenant_id, platform, platform_order_id)
        );

        COMMENT ON TABLE delivery_orders IS
            '外卖平台订单统一存储：美团/饿了么/抖音订单均写入此表，保留原始 payload';
        COMMENT ON COLUMN delivery_orders.items IS
            'JSONB 数组：[{dish_id, name, qty, unit_price_fen, spec, ...}]';
        COMMENT ON COLUMN delivery_orders.total_fen IS
            '订单总金额，单位：分（避免浮点精度问题）';
        COMMENT ON COLUMN delivery_orders.commission_fen IS
            '平台佣金金额，单位：分（由 total_fen × commission_rate 计算）';
        COMMENT ON COLUMN delivery_orders.raw_payload IS
            '平台原始推送 payload，用于对账和问题排查';

        CREATE INDEX IF NOT EXISTS ix_delivery_orders_tenant_store_status
            ON delivery_orders (tenant_id, store_id, status)
            WHERE is_deleted = FALSE;

        CREATE INDEX IF NOT EXISTS ix_delivery_orders_tenant_platform_created
            ON delivery_orders (tenant_id, platform, created_at DESC)
            WHERE is_deleted = FALSE;

        CREATE INDEX IF NOT EXISTS ix_delivery_orders_internal_order
            ON delivery_orders (internal_order_id)
            WHERE internal_order_id IS NOT NULL;
    """)

    # RLS: delivery_orders
    op.execute("""
        ALTER TABLE delivery_orders ENABLE ROW LEVEL SECURITY;
        ALTER TABLE delivery_orders FORCE ROW LEVEL SECURITY;

        CREATE POLICY delivery_orders_tenant_isolation
            ON delivery_orders
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

    # ─────────────────────────────────────────────────────────────────
    # 3. delivery_platform_items — 外卖平台商品映射
    #    内部菜品 dish_id ↔ 各平台 SKU 的映射关系和价格管理
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS delivery_platform_items (
            id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID        NOT NULL,
            store_id          UUID        NOT NULL,
            platform          VARCHAR(20) NOT NULL
                CHECK (platform IN ('meituan', 'eleme', 'douyin')),
            dish_id           UUID        NOT NULL,
            platform_item_id  VARCHAR(100) NOT NULL,
            platform_name     VARCHAR(200) NOT NULL,
            platform_price    INT         NOT NULL DEFAULT 0,   -- 平台售价（分）
            is_active         BOOLEAN     NOT NULL DEFAULT TRUE,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted        BOOLEAN     NOT NULL DEFAULT FALSE,

            CONSTRAINT uq_delivery_platform_items_platform_item
                UNIQUE (tenant_id, store_id, platform, platform_item_id)
        );

        COMMENT ON TABLE delivery_platform_items IS
            '外卖平台商品映射：内部 dish_id ↔ 各平台 SKU，支持独立定价';
        COMMENT ON COLUMN delivery_platform_items.platform_price IS
            '平台售价，单位：分。可与堂食价格不同';

        CREATE INDEX IF NOT EXISTS ix_delivery_platform_items_dish
            ON delivery_platform_items (tenant_id, dish_id, platform)
            WHERE is_deleted = FALSE AND is_active = TRUE;

        CREATE INDEX IF NOT EXISTS ix_delivery_platform_items_platform
            ON delivery_platform_items (tenant_id, store_id, platform)
            WHERE is_deleted = FALSE;
    """)

    # RLS: delivery_platform_items
    op.execute("""
        ALTER TABLE delivery_platform_items ENABLE ROW LEVEL SECURITY;
        ALTER TABLE delivery_platform_items FORCE ROW LEVEL SECURITY;

        CREATE POLICY delivery_platform_items_tenant_isolation
            ON delivery_platform_items
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
    op.execute("""
        DROP TABLE IF EXISTS delivery_platform_items;
        DROP TABLE IF EXISTS delivery_orders;
        DROP TABLE IF EXISTS delivery_platform_configs;
    """)
