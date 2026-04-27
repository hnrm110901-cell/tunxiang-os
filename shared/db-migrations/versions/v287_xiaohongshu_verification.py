"""v287 — 小红书核销对接（Sprint E3）

目标：打通小红书团购核销链路
  1. 商户授权（OAuth 2.0）→ 存 access_token / refresh_token
  2. 小红书推核销 webhook → 签名校验 → 去重 → 走 E1 canonical transform

两表：
  · `xiaohongshu_shop_bindings` — store_id ↔ 小红书 shop_code 绑定 + OAuth token
    · 同租户同 store_id 只能绑一个 shop_code（UNIQUE）
    · token 到期时间字段用于刷新判断
  · `xiaohongshu_verify_events` — webhook 原始事件归档
    · payload_sha256 UNIQUE 去重
    · transform_status 跟踪是否成功转成 canonical
    · 失败事件保留 raw_payload 供重放

与 E1/E2 的关系：
  · `canonical_delivery_orders.platform = 'xiaohongshu'` 的订单由本 PR 的
    webhook 端点写入
  · `dish_publish_registry.platform = 'xiaohongshu'` 由 E2 团购 SKU 创建

Revision ID: v287_xhs_verify
Revises: v286_dish_publish
Create Date: 2026-04-24
"""
from alembic import op

revision = "v287_xhs_verify"
down_revision = "v286_dish_publish"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── xiaohongshu_shop_bindings ─────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS xiaohongshu_shop_bindings (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            store_id                UUID NOT NULL,
            brand_id                UUID,
            -- 小红书侧标识
            xhs_shop_code           VARCHAR(64) NOT NULL,
                                    -- 平台门店编码
            xhs_merchant_id         VARCHAR(64) NOT NULL,
                                    -- 商户（多店共用一个商户号）
            xhs_shop_name           VARCHAR(200),
            -- OAuth token（敏感：存前端脱敏；后端用 KMS 加密，此处存密文）
            access_token            TEXT,
                                    -- Bearer token，调平台 API 用
            refresh_token           TEXT,
                                    -- 刷新凭证（有效期更长）
            token_expires_at        TIMESTAMPTZ,
                                    -- access_token 到期时间
            scope                   VARCHAR(200),
                                    -- OAuth scope 列表（space-delimited）
            -- webhook 校验
            webhook_secret          VARCHAR(128) NOT NULL,
                                    -- 用于 HMAC-SHA256 签名校验（小红书管理后台下发）
            webhook_url             TEXT,
                                    -- 回推地址（商户配置到小红书后台的）
            -- 状态
            status                  VARCHAR(30) NOT NULL DEFAULT 'pending'
                                    CHECK (status IN (
                                        'pending',      -- 待授权
                                        'active',       -- 授权中
                                        'expired',      -- token 过期需重新授权
                                        'suspended',    -- 被平台暂停
                                        'unbound'       -- 商家主动解绑
                                    )),
            last_webhook_at         TIMESTAMPTZ,
                                    -- 最近收到 webhook 时间（监控绑定是否活跃）
            consecutive_auth_errors INTEGER NOT NULL DEFAULT 0,
                                    -- 连续 401 计数，> 3 次触发 expired 状态
            -- 基础
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    # 同租户同 store 只能绑一个 xhs_shop_code
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_xhs_bindings_store
            ON xiaohongshu_shop_bindings (tenant_id, store_id)
            WHERE is_deleted = false
    """)
    # 反查：用 xhs_shop_code 找 store（webhook 必需）
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_xhs_bindings_shop_code
            ON xiaohongshu_shop_bindings (tenant_id, xhs_shop_code)
            WHERE is_deleted = false
    """)
    # 状态 + 需刷新 token 的过滤
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_xhs_bindings_status
            ON xiaohongshu_shop_bindings (tenant_id, status, token_expires_at)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE xiaohongshu_shop_bindings ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS xhs_bindings_tenant_isolation ON xiaohongshu_shop_bindings;
        CREATE POLICY xhs_bindings_tenant_isolation ON xiaohongshu_shop_bindings
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ── xiaohongshu_verify_events ─────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS xiaohongshu_verify_events (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            binding_id              UUID,
                                    -- 对应的 xiaohongshu_shop_bindings.id
                                    -- NULL 可能是无效 shop_code 的攻击 / 错配，保留审计
            store_id                UUID,
            -- 事件识别
            event_type              VARCHAR(50) NOT NULL,
                                    -- verify_success / verify_cancel / refund /
                                    -- status_update / unknown
            verify_code             VARCHAR(100),
                                    -- 团购核销码（XHS xxxxxx）
            xhs_shop_code           VARCHAR(64),
            xhs_order_id            VARCHAR(100),
            -- 原始 payload + 幂等
            raw_payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
            payload_sha256          VARCHAR(64) NOT NULL,
            received_headers        JSONB NOT NULL DEFAULT '{}'::jsonb,
                                    -- X-Xhs-Signature / X-Xhs-Timestamp / Nonce
            -- 签名校验
            signature_valid         BOOLEAN,
                                    -- NULL = 未校验；true/false = 校验结果
            signature_error         TEXT,
                                    -- 签名错误原因（timestamp_too_old / hmac_mismatch / 等）
            -- canonical 转换跟踪
            transform_status        VARCHAR(30) NOT NULL DEFAULT 'pending'
                                    CHECK (transform_status IN (
                                        'pending',        -- 待转换
                                        'transformed',    -- 已转 canonical + 持久化
                                        'skipped',        -- 签名失败 / 重复事件，不处理
                                        'failed',         -- 转换失败，需排查
                                        'replayed'        -- 人工重放成功
                                    )),
            canonical_order_id      UUID,
                                    -- 成功时指向 canonical_delivery_orders.id
            transform_error         TEXT,
            -- 审计
            received_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            processed_at            TIMESTAMPTZ,
            source_ip               INET,
            -- 基础
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # 幂等：同 payload 只存一条
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_xhs_verify_events_sha
            ON xiaohongshu_verify_events (tenant_id, payload_sha256)
    """)
    # 按 binding 拉历史
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_xhs_verify_events_binding
            ON xiaohongshu_verify_events (binding_id, received_at DESC)
            WHERE binding_id IS NOT NULL
    """)
    # 失败事件快速定位
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_xhs_verify_events_failed
            ON xiaohongshu_verify_events (tenant_id, transform_status, received_at DESC)
            WHERE transform_status IN ('failed', 'skipped')
    """)
    # verify_code 反查（核销码可能被多次推送）
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_xhs_verify_events_code
            ON xiaohongshu_verify_events (tenant_id, verify_code, received_at DESC)
            WHERE verify_code IS NOT NULL
    """)

    op.execute("ALTER TABLE xiaohongshu_verify_events ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS xhs_verify_events_tenant_isolation ON xiaohongshu_verify_events;
        CREATE POLICY xhs_verify_events_tenant_isolation ON xiaohongshu_verify_events
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # 注释
    op.execute("""
        COMMENT ON TABLE xiaohongshu_shop_bindings IS
            'Sprint E3: 小红书商户绑定 + OAuth token + webhook_secret';
        COMMENT ON COLUMN xiaohongshu_shop_bindings.webhook_secret IS
            '小红书后台生成的签名密钥，用于 HMAC-SHA256 校验 webhook';
        COMMENT ON COLUMN xiaohongshu_shop_bindings.consecutive_auth_errors IS
            '连续 401 错误计数，> 3 次自动转 expired 并要求重新授权';
        COMMENT ON TABLE xiaohongshu_verify_events IS
            'Sprint E3: 小红书 webhook 原始事件归档 — payload 保真 + 签名校验结果 + canonical 转换跟踪';
        COMMENT ON COLUMN xiaohongshu_verify_events.transform_status IS
            'pending / transformed / skipped（签名失败/重复）/ failed / replayed';
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS xiaohongshu_verify_events CASCADE")
    op.execute("DROP TABLE IF EXISTS xiaohongshu_shop_bindings CASCADE")
