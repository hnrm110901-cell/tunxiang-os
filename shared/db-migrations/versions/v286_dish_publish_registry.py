"""v286 — 菜品一键发布注册表（Sprint E2）

目标：一套菜品配置同步发布到 5 平台（美团/饿了么/抖音/小红书/微信），避免商家
     重复录入上架信息。状态 / 价格 / 库存三组同步动作各有独立事务。

两表设计：
  1. `dish_publish_registry` — 一条 = (dish × platform) 当前状态快照
     · UNIQUE (tenant, dish, platform)：每菜每平台只一条
     · 记录 target_price_fen / published_price_fen 区分"商家要的价"与"平台确认的价"
     · stock 类似（target vs available）
  2. `dish_publish_tasks` — 异步任务队列（每次 publish / update_price 调用产生）
     · 支持 attempts 重试 + scheduled_for 延时调度
     · 与 registry 1:N

工作流：
  1. CFO / 店长在 admin 界面改菜品价格 5000 → 5500
  2. API 调 `POST /publish/{dish_id}/price {price_fen: 5500, platforms: [...]}`
  3. Orchestrator 更新每条 registry 的 target_price_fen + 插入 5 条 publish_task
  4. Worker 消费 task，调各平台 Publisher SDK
  5. 成功：registry.published_price_fen = 5500 + status=published
     失败：registry.last_error + error_count++ + task.status=failed

与 E1 canonical schema 的关系：
  · canonical_delivery_orders.platform_sku_id ← dish_publish_registry.platform_sku_id
    通过这个链路，分析层能把外卖订单的 SKU 回溯到内部 dish

Revision ID: v286_dish_publish
Revises: v285_canonical_delivery
Create Date: 2026-04-24
"""
from alembic import op

revision = "v286_dish_publish"
down_revision = "v285_canonical_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── dish_publish_registry ─────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS dish_publish_registry (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            dish_id                 UUID NOT NULL,
            brand_id                UUID,
            store_id                UUID,
                                    -- NULL = 品牌级统一发布；非 NULL = 单店发布
            -- 平台
            platform                VARCHAR(20) NOT NULL
                                    CHECK (platform IN (
                                        'meituan', 'eleme', 'douyin',
                                        'xiaohongshu', 'wechat', 'other'
                                    )),
            platform_sku_id         VARCHAR(100),
                                    -- 平台首次发布成功后回填
            platform_shop_id        VARCHAR(100),
                                    -- 平台门店 ID（meituan poiId / eleme shop_id）
            -- 状态
            status                  VARCHAR(30) NOT NULL DEFAULT 'pending'
                                    CHECK (status IN (
                                        'pending',       -- 等待首次发布
                                        'publishing',    -- 发布中（worker 处理）
                                        'published',     -- 已上架
                                        'paused',        -- 暂停售卖（商家手动）
                                        'sold_out',      -- 已售罄（库存=0）
                                        'unpublished',   -- 已下架
                                        'error'          -- 持续失败
                                    )),
            -- 价格（fen）
            target_price_fen        BIGINT NOT NULL DEFAULT 0
                                    CHECK (target_price_fen >= 0),
                                    -- 商家期望价
            published_price_fen     BIGINT,
                                    -- 平台确认后的价（可能因促销被平台调整）
            original_price_fen      BIGINT,
                                    -- 平台"划线价"，用于显示优惠
            -- 库存
            stock_target            INTEGER,
                                    -- 商家设置；NULL = 不限库存
            stock_available         INTEGER,
                                    -- 平台确认后的库存
            -- 同步状态
            last_sync_at            TIMESTAMPTZ,
            last_sync_operation     VARCHAR(30),
                                    -- publish / update_price / update_stock / pause / resume / unpublish
            last_error              TEXT,
            error_count             INTEGER NOT NULL DEFAULT 0
                                    CHECK (error_count >= 0),
            consecutive_error_count INTEGER NOT NULL DEFAULT 0
                                    CHECK (consecutive_error_count >= 0),
                                    -- 连续失败 → 触发告警；成功 reset
            -- 平台回传 metadata
            platform_metadata       JSONB NOT NULL DEFAULT '{}'::jsonb,
            -- 基础字段
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    # 一菜一平台只一条
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_dish_publish_registry_unique
            ON dish_publish_registry (
                tenant_id,
                dish_id,
                platform,
                COALESCE(store_id, '00000000-0000-0000-0000-000000000000'::uuid)
            )
            WHERE is_deleted = false
    """)
    # 查询：按 dish 拉全平台快照
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_dish_publish_registry_dish
            ON dish_publish_registry (tenant_id, dish_id, platform)
            WHERE is_deleted = false
    """)
    # 告警：连续失败的 registry
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_dish_publish_registry_errors
            ON dish_publish_registry (tenant_id, consecutive_error_count DESC)
            WHERE is_deleted = false AND consecutive_error_count > 0
    """)
    # 平台反查：用 platform_sku_id 找 dish（canonical_delivery_items 消费）
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_dish_publish_registry_sku
            ON dish_publish_registry (tenant_id, platform, platform_sku_id)
            WHERE is_deleted = false AND platform_sku_id IS NOT NULL
    """)

    op.execute("ALTER TABLE dish_publish_registry ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS dish_publish_registry_tenant_isolation
            ON dish_publish_registry;
        CREATE POLICY dish_publish_registry_tenant_isolation ON dish_publish_registry
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ── dish_publish_tasks（异步队列）──────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS dish_publish_tasks (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            registry_id              UUID NOT NULL
                                    REFERENCES dish_publish_registry(id)
                                    ON DELETE CASCADE,
            dish_id                 UUID NOT NULL,
            platform                VARCHAR(20) NOT NULL,
            -- 操作
            operation               VARCHAR(30) NOT NULL
                                    CHECK (operation IN (
                                        'publish',        -- 首次上架
                                        'update_price',
                                        'update_stock',
                                        'update_full',    -- 价 + 库存 + metadata 全量
                                        'pause',
                                        'resume',
                                        'unpublish'
                                    )),
            payload                 JSONB NOT NULL DEFAULT '{}'::jsonb,
                                    -- {price_fen, stock, reason, ...}
            -- 队列状态
            status                  VARCHAR(30) NOT NULL DEFAULT 'queued'
                                    CHECK (status IN (
                                        'queued',
                                        'running',
                                        'completed',
                                        'failed',
                                        'cancelled'
                                    )),
            -- 重试
            attempts                INTEGER NOT NULL DEFAULT 0
                                    CHECK (attempts >= 0),
            max_attempts            INTEGER NOT NULL DEFAULT 3
                                    CHECK (max_attempts > 0),
            scheduled_for           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            started_at              TIMESTAMPTZ,
            completed_at            TIMESTAMPTZ,
            -- 结果
            error_message           TEXT,
            platform_response       JSONB,
                                    -- 成功时存 platform_sku_id 等；失败时存 error code
            -- 审计
            triggered_by            UUID,
                                    -- 操作员 ID（manual trigger）或 NULL（cron）
            trigger_source          VARCHAR(30) NOT NULL DEFAULT 'api'
                                    CHECK (trigger_source IN (
                                        'api', 'cron', 'backfill', 'replay'
                                    )),
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # Worker 拉队列：按 scheduled_for 顺序
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_dish_publish_tasks_queue
            ON dish_publish_tasks (scheduled_for, id)
            WHERE status = 'queued'
    """)
    # 审计：按 registry 拉历史
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_dish_publish_tasks_registry
            ON dish_publish_tasks (registry_id, created_at DESC)
    """)
    # 监控：最近失败任务
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_dish_publish_tasks_failed
            ON dish_publish_tasks (tenant_id, status, created_at DESC)
            WHERE status = 'failed'
    """)

    op.execute("ALTER TABLE dish_publish_tasks ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS dish_publish_tasks_tenant_isolation ON dish_publish_tasks;
        CREATE POLICY dish_publish_tasks_tenant_isolation ON dish_publish_tasks
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # 注释
    op.execute("""
        COMMENT ON TABLE dish_publish_registry IS
            'Sprint E2: 菜品一键发布注册表 — 一菜一平台一条，记录当前发布状态/价/库存';
        COMMENT ON COLUMN dish_publish_registry.target_price_fen IS
            '商家期望价（fen）；published_price_fen 是平台实际接受的价';
        COMMENT ON COLUMN dish_publish_registry.consecutive_error_count IS
            '连续失败次数（成功后 reset）— > 5 次触发告警';
        COMMENT ON TABLE dish_publish_tasks IS
            'Sprint E2: 菜品发布异步任务队列 — worker 消费后调各平台 Publisher';
        COMMENT ON COLUMN dish_publish_tasks.operation IS
            'publish / update_price / update_stock / update_full / pause / resume / unpublish';
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dish_publish_tasks CASCADE")
    op.execute("DROP TABLE IF EXISTS dish_publish_registry CASCADE")
