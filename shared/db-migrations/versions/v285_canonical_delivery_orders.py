"""v285 — 外卖 canonical schema（Sprint E1）

目标：把 5 个平台（美团/饿了么/抖音/小红书/微信）千差万别的订单 payload 规范化
     到统一的 canonical schema，下游分析 / Agent / BI 只认 canonical，不碰平台。

设计原则：
  1. **raw_payload 保真归档** — 每一条 canonical 都附带原始推送，永不丢
  2. **幂等**：payload_sha256 UNIQUE，重复推送自动去重
  3. **状态机统一**：pending/accepted/preparing/dispatched/delivering/delivered/
     cancelled/refunded —— 平台原状态串存 `platform_status_raw`
  4. **金额统一分（fen）为 BIGINT**：无浮点、无币种歧义
  5. **versioning**：`canonical_version` 预留字段，未来 schema 升级时增量迁移

与现有 `delivery_orders` 表的关系：
  · 现 `delivery_orders` 是 v058 引入的"平台原始订单镜像"，字段偏平台原生
  · `canonical_delivery_orders` 是统一视图，一对一 OR 一对多（同一订单被多平台推送时）
  · 两表通过 `platform + platform_order_id` 关联，不强制外键（允许独立演进）

Revision ID: v285_canonical_delivery
Revises: v284_coupon_materialized_views
Create Date: 2026-04-23
"""
from alembic import op

revision = "v285_canonical_delivery"
down_revision = "v284_coupon_materialized_views"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── canonical_delivery_orders ─────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS canonical_delivery_orders (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            -- 内部编号
            canonical_order_no      VARCHAR(40) NOT NULL,
                                    -- CNL + YYYYMMDD + 随机 (eg CNL20260423A7F3)
            -- 平台识别
            platform                VARCHAR(20) NOT NULL
                                    CHECK (platform IN (
                                        'meituan',       -- 美团外卖
                                        'eleme',         -- 饿了么
                                        'douyin',        -- 抖音外卖
                                        'xiaohongshu',   -- 小红书（到店 / 团购核销）
                                        'wechat',        -- 微信小程序自营
                                        'other'          -- 兜底，raw_payload 需完整
                                    )),
            platform_order_id       VARCHAR(100) NOT NULL,
            platform_sub_type       VARCHAR(30),
                                    -- meituan_delivery / meituan_dine_in /
                                    -- douyin_group_buy / eleme_b2c 等
            -- 门店
            store_id                UUID,
            brand_id                UUID,
            -- 订单类型 / 状态（canonical）
            order_type              VARCHAR(20) NOT NULL DEFAULT 'delivery'
                                    CHECK (order_type IN (
                                        'delivery',     -- 外送
                                        'pickup',       -- 自取
                                        'dine_in',      -- 到店
                                        'group_buy'     -- 团购核销
                                    )),
            status                  VARCHAR(30) NOT NULL DEFAULT 'pending'
                                    CHECK (status IN (
                                        'pending',      -- 待商家接单
                                        'accepted',     -- 已接单
                                        'preparing',    -- 出品中
                                        'dispatched',   -- 已出餐（待骑手取）
                                        'delivering',   -- 配送中
                                        'delivered',    -- 已送达
                                        'completed',    -- 已完成（含到店核销结束）
                                        'cancelled',
                                        'refunded',
                                        'error'
                                    )),
            platform_status_raw     VARCHAR(100),
                                    -- 原始平台状态，例如 meituan 的 '已完成', 抖音的 4
            -- 顾客（PII 脱敏）
            customer_name           VARCHAR(100),
            customer_phone_masked   VARCHAR(32),
                                    -- 138****5678 格式
            customer_address        TEXT,
                                    -- 明文留给平台授权范围内使用
            customer_address_hash   VARCHAR(64),
                                    -- sha256，用于重复检测 + 去重
            -- 金额（全 fen / BIGINT）
            gross_amount_fen        BIGINT NOT NULL DEFAULT 0
                                    CHECK (gross_amount_fen >= 0),
                                    -- 商品原价合计
            discount_amount_fen     BIGINT NOT NULL DEFAULT 0
                                    CHECK (discount_amount_fen >= 0),
                                    -- 所有优惠（平台 + 商家 + 会员）
            platform_commission_fen BIGINT NOT NULL DEFAULT 0,
                                    -- 平台抽佣（商家扣减）
            platform_subsidy_fen    BIGINT NOT NULL DEFAULT 0
                                    CHECK (platform_subsidy_fen >= 0),
                                    -- 平台补贴（商家应得）
            delivery_fee_fen        BIGINT NOT NULL DEFAULT 0
                                    CHECK (delivery_fee_fen >= 0),
                                    -- 顾客付配送费
            delivery_cost_fen       BIGINT NOT NULL DEFAULT 0,
                                    -- 商家实际承担配送成本
            packaging_fee_fen       BIGINT NOT NULL DEFAULT 0
                                    CHECK (packaging_fee_fen >= 0),
            tax_fen                 BIGINT NOT NULL DEFAULT 0,
            tip_fen                 BIGINT NOT NULL DEFAULT 0
                                    CHECK (tip_fen >= 0),
            paid_amount_fen         BIGINT NOT NULL DEFAULT 0
                                    CHECK (paid_amount_fen >= 0),
                                    -- 顾客实付
            net_amount_fen          BIGINT NOT NULL DEFAULT 0,
                                    -- 商家实收 = gross - discount - commission + subsidy
                                    -- （可负，退款场景）
            -- 时间轴
            placed_at               TIMESTAMPTZ NOT NULL,
                                    -- 下单时间（canonical 必需）
            accepted_at             TIMESTAMPTZ,
            dispatched_at           TIMESTAMPTZ,
            delivered_at            TIMESTAMPTZ,
            completed_at            TIMESTAMPTZ,
            cancelled_at            TIMESTAMPTZ,
            expected_delivery_at    TIMESTAMPTZ,
            -- 原始保真 + 幂等
            raw_payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
            payload_sha256          VARCHAR(64) NOT NULL,
                                    -- 基于 raw_payload 计算，UNIQUE 保证幂等
            platform_metadata       JSONB NOT NULL DEFAULT '{}'::jsonb,
                                    -- 平台特定字段存活（如美团 shipping_service_code）
            transformation_errors   JSONB NOT NULL DEFAULT '[]'::jsonb,
                                    -- 转换时发现的 non-critical 问题列表
            canonical_version       INTEGER NOT NULL DEFAULT 1,
                                    -- schema 版本，未来升级时批量回填
            -- 审计
            ingested_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            ingested_by             VARCHAR(100) NOT NULL DEFAULT 'webhook',
                                    -- webhook / manual / backfill
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    # 幂等：同租户同平台同 platform_order_id 只存一条（即便多次推送）
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_canonical_delivery_platform_order
            ON canonical_delivery_orders (tenant_id, platform, platform_order_id)
            WHERE is_deleted = false
    """)
    # 幂等：同一 payload 去重
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_canonical_delivery_payload_sha
            ON canonical_delivery_orders (tenant_id, payload_sha256)
            WHERE is_deleted = false
    """)
    # 查询：门店 + 时间倒序
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_canonical_delivery_store_time
            ON canonical_delivery_orders (tenant_id, store_id, placed_at DESC)
            WHERE is_deleted = false
    """)
    # 查询：状态 + 时间（用于 KDS / 待接单队列）
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_canonical_delivery_status_time
            ON canonical_delivery_orders (tenant_id, status, placed_at DESC)
            WHERE is_deleted = false AND status IN ('pending', 'accepted', 'preparing', 'dispatched', 'delivering')
    """)
    # 内部编号查找
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_canonical_delivery_no
            ON canonical_delivery_orders (tenant_id, canonical_order_no)
            WHERE is_deleted = false
    """)

    # RLS
    op.execute("ALTER TABLE canonical_delivery_orders ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS canonical_delivery_tenant_isolation ON canonical_delivery_orders;
        CREATE POLICY canonical_delivery_tenant_isolation ON canonical_delivery_orders
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ── canonical_delivery_items ──────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS canonical_delivery_items (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            order_id                UUID NOT NULL
                                    REFERENCES canonical_delivery_orders(id)
                                    ON DELETE CASCADE,
            -- 商品标识
            platform_sku_id         VARCHAR(100),
                                    -- 平台原 SKU（用于跨平台比对）
            internal_dish_id        UUID,
                                    -- 映射到内部 Dish（匹配失败 = NULL）
            dish_name_platform      VARCHAR(200) NOT NULL,
                                    -- 平台展示名
            dish_name_canonical     VARCHAR(200),
                                    -- 内部规范化名（可后补）
            -- 数量 / 金额（fen）
            quantity                INTEGER NOT NULL CHECK (quantity > 0),
            unit_price_fen          BIGINT NOT NULL DEFAULT 0
                                    CHECK (unit_price_fen >= 0),
            subtotal_fen            BIGINT NOT NULL DEFAULT 0
                                    CHECK (subtotal_fen >= 0),
                                    -- unit_price * quantity
            discount_amount_fen     BIGINT NOT NULL DEFAULT 0
                                    CHECK (discount_amount_fen >= 0),
            total_fen               BIGINT NOT NULL DEFAULT 0,
                                    -- subtotal - discount
            -- 规格 / 做法 / 备注
            modifiers               JSONB NOT NULL DEFAULT '[]'::jsonb,
                                    -- [{name: "辣度", value: "中辣"}, ...]
            notes                   TEXT,
            -- 顺序
            line_no                 INTEGER NOT NULL DEFAULT 1,
            -- 审计
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_canonical_delivery_items_order
            ON canonical_delivery_items (order_id, line_no)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_canonical_delivery_items_dish
            ON canonical_delivery_items (tenant_id, internal_dish_id)
            WHERE is_deleted = false AND internal_dish_id IS NOT NULL
    """)

    op.execute("ALTER TABLE canonical_delivery_items ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS canonical_delivery_items_tenant_isolation ON canonical_delivery_items;
        CREATE POLICY canonical_delivery_items_tenant_isolation ON canonical_delivery_items
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # 注释
    op.execute("""
        COMMENT ON TABLE canonical_delivery_orders IS
            'Sprint E1: 外卖 canonical schema — 5 平台（美团/饿了么/抖音/小红书/微信）
             统一订单视图，raw_payload 保真归档，payload_sha256 保证幂等';
        COMMENT ON COLUMN canonical_delivery_orders.status IS
            'canonical: pending/accepted/preparing/dispatched/delivering/delivered/completed/cancelled/refunded/error';
        COMMENT ON COLUMN canonical_delivery_orders.payload_sha256 IS
            '基于 raw_payload 计算，UNIQUE 约束实现幂等推送（重复 webhook 自动去重）';
        COMMENT ON COLUMN canonical_delivery_orders.canonical_version IS
            'schema 版本号，未来字段升级时用于批量回填标识';
        COMMENT ON COLUMN canonical_delivery_orders.transformation_errors IS
            '[{field, raw_value, reason}] 记录 transformation 过程中 non-critical 问题';
        COMMENT ON TABLE canonical_delivery_items IS
            '外卖 canonical items — 一对多附属于 canonical_delivery_orders';
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS canonical_delivery_items CASCADE")
    op.execute("DROP TABLE IF EXISTS canonical_delivery_orders CASCADE")
