"""v288 — 外卖异议工作流（Sprint E4，Sprint E 收官）

场景：
  顾客投诉（漏菜/异物/超时/菜凉/错单/质量/包装/账单错误）→ 平台退款请求
  → 商家 24h 内必须响应 → 平台裁定 → 资金流转

两表：
  · `delivery_disputes` — 一条 = 一个异议事件
    · UNIQUE (tenant, platform, platform_dispute_id) 幂等
    · status 状态机 12 态，含 SLA 过期自动态
    · 分别记录顾客诉求金额 / 商家 offered 金额 / 平台裁定金额
  · `delivery_dispute_messages` — 会话流水
    · customer/merchant/platform/agent 四方消息
    · 用于审计 + 自动响应模板上下文抽取

与 E1 canonical 的关系：
  · disputes.canonical_order_id 可选 FK 到 canonical_delivery_orders
  · platform_order_id + platform 作为业务键关联

Revision ID: v288_delivery_disputes
Revises: v287_xhs_verify
Create Date: 2026-04-24
"""
from alembic import op

revision = "v288_delivery_disputes"
down_revision = "v287_xhs_verify"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── delivery_disputes ─────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS delivery_disputes (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            canonical_order_id      UUID,
                                    -- 软 FK 到 canonical_delivery_orders.id
                                    -- NULL 表示商家手动创建或 canonical 还未落盘
            platform                VARCHAR(20) NOT NULL
                                    CHECK (platform IN (
                                        'meituan', 'eleme', 'douyin',
                                        'xiaohongshu', 'wechat', 'other'
                                    )),
            platform_dispute_id     VARCHAR(100) NOT NULL,
                                    -- 平台侧异议单号
            platform_order_id       VARCHAR(100) NOT NULL,
                                    -- 原始订单号（用于 join canonical）
            store_id                UUID,
            brand_id                UUID,
            -- 异议类型与诉求
            dispute_type            VARCHAR(30) NOT NULL DEFAULT 'other'
                                    CHECK (dispute_type IN (
                                        'quality_issue',  -- 质量问题（味道差/变质）
                                        'missing_item',   -- 漏菜
                                        'wrong_item',     -- 送错菜
                                        'foreign_object', -- 异物
                                        'late_delivery',  -- 超时
                                        'cold_food',      -- 菜凉
                                        'packaging',      -- 包装破损/洒漏
                                        'billing_error',  -- 账单错误
                                        'portion_size',   -- 份量不足
                                        'service',        -- 服务态度
                                        'other'
                                    )),
            dispute_reason          TEXT,
            customer_claim_amount_fen BIGINT
                                    CHECK (customer_claim_amount_fen IS NULL
                                           OR customer_claim_amount_fen >= 0),
            customer_evidence_urls  JSONB NOT NULL DEFAULT '[]'::jsonb,
            -- 状态机
            status                  VARCHAR(30) NOT NULL DEFAULT 'opened'
                                    CHECK (status IN (
                                        'opened',              -- 平台新收到
                                        'pending_merchant',    -- 等商家响应
                                        'merchant_accepted',   -- 商家同意全额退
                                        'merchant_offered',    -- 商家提出部分退款
                                        'merchant_disputed',   -- 商家申辩无责
                                        'platform_reviewing',  -- 平台审核中
                                        'resolved_refund_full',-- 裁定全额退款
                                        'resolved_refund_partial',
                                        'resolved_merchant_win',
                                        'withdrawn',           -- 顾客撤诉
                                        'escalated',           -- 升级
                                        'expired',             -- SLA 超时（自动）
                                        'error'
                                    )),
            -- SLA
            raised_at               TIMESTAMPTZ NOT NULL,
                                    -- 顾客发起时间（平台推送）
            merchant_deadline_at    TIMESTAMPTZ NOT NULL,
                                    -- 商家响应截止（默认 raised_at + 24h）
            sla_breached            BOOLEAN NOT NULL DEFAULT FALSE,
                                    -- 过期后 cron 回扫设 true
            -- 商家响应
            merchant_response_template_id VARCHAR(50),
            merchant_response       TEXT,
            merchant_offered_refund_fen BIGINT
                                    CHECK (merchant_offered_refund_fen IS NULL
                                           OR merchant_offered_refund_fen >= 0),
            merchant_evidence_urls  JSONB NOT NULL DEFAULT '[]'::jsonb,
            merchant_responded_at   TIMESTAMPTZ,
            responded_by            UUID,
                                    -- 操作员
            -- 平台裁决
            platform_decision       TEXT,
            platform_refund_fen     BIGINT
                                    CHECK (platform_refund_fen IS NULL
                                           OR platform_refund_fen >= 0),
            platform_ruled_at       TIMESTAMPTZ,
            -- 终态时间
            closed_at               TIMESTAMPTZ,
            -- 审计
            source                  VARCHAR(30) NOT NULL DEFAULT 'webhook'
                                    CHECK (source IN (
                                        'webhook', 'manual', 'backfill', 'replay'
                                    )),
            raw_payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
            -- 基础
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    # 幂等：平台 dispute_id 唯一
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_delivery_disputes_platform_id
            ON delivery_disputes (tenant_id, platform, platform_dispute_id)
            WHERE is_deleted = false
    """)
    # 关联 canonical 订单查历史
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_delivery_disputes_canonical
            ON delivery_disputes (tenant_id, canonical_order_id)
            WHERE is_deleted = false AND canonical_order_id IS NOT NULL
    """)
    # 运营待办队列：pending_merchant + merchant_deadline_at 升序（先过期的先处理）
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_delivery_disputes_pending_sla
            ON delivery_disputes (tenant_id, merchant_deadline_at)
            WHERE is_deleted = false AND status = 'pending_merchant'
    """)
    # SLA 超时扫描：SLA 已过但仍 pending
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_delivery_disputes_breached
            ON delivery_disputes (tenant_id, status, merchant_deadline_at)
            WHERE is_deleted = false AND sla_breached = false
              AND status IN ('opened', 'pending_merchant')
    """)
    # 按门店 + 时间倒序
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_delivery_disputes_store_time
            ON delivery_disputes (tenant_id, store_id, raised_at DESC)
            WHERE is_deleted = false
    """)
    # 按 platform + status 聚合报表
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_delivery_disputes_platform_status
            ON delivery_disputes (tenant_id, platform, status, raised_at DESC)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE delivery_disputes ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS delivery_disputes_tenant_isolation
            ON delivery_disputes;
        CREATE POLICY delivery_disputes_tenant_isolation ON delivery_disputes
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ── delivery_dispute_messages ─────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS delivery_dispute_messages (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            dispute_id              UUID NOT NULL
                                    REFERENCES delivery_disputes(id)
                                    ON DELETE CASCADE,
            -- 发送方 & 类型
            sender_role             VARCHAR(30) NOT NULL
                                    CHECK (sender_role IN (
                                        'customer',   -- 顾客
                                        'merchant',   -- 商家（含员工）
                                        'platform',   -- 平台客服
                                        'agent',      -- AI Agent 自动回复
                                        'system'      -- 系统通知
                                    )),
            sender_id               VARCHAR(100),
                                    -- 操作员 UUID / 平台客服 ID / 顾客 openid
            message_type            VARCHAR(30) NOT NULL DEFAULT 'text'
                                    CHECK (message_type IN (
                                        'text', 'image', 'video',
                                        'system_note', 'refund_offer',
                                        'ruling'
                                    )),
            content                 TEXT,
            attachment_urls         JSONB NOT NULL DEFAULT '[]'::jsonb,
            -- 关联的 offer（商家提出的退款数字）
            linked_refund_fen       BIGINT,
            -- 时间
            sent_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            -- 原始 payload（平台推送的原文）
            raw_payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
            -- 基础
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_dispute_messages_dispute
            ON delivery_dispute_messages (dispute_id, sent_at)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_dispute_messages_sender_role
            ON delivery_dispute_messages (tenant_id, sender_role, sent_at DESC)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE delivery_dispute_messages ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS dispute_messages_tenant_isolation
            ON delivery_dispute_messages;
        CREATE POLICY dispute_messages_tenant_isolation
            ON delivery_dispute_messages
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # 注释
    op.execute("""
        COMMENT ON TABLE delivery_disputes IS
            'Sprint E4: 外卖异议工作流 — 顾客投诉 → 商家响应 → 平台裁定 全链路';
        COMMENT ON COLUMN delivery_disputes.status IS
            'opened → pending_merchant → merchant_{accepted|offered|disputed}
             → platform_reviewing → resolved_{refund_full|refund_partial|merchant_win}
             (+ withdrawn/escalated/expired/error 终态)';
        COMMENT ON COLUMN delivery_disputes.sla_breached IS
            'cron 定期扫 pending_merchant 且 NOW() > merchant_deadline_at 的记录';
        COMMENT ON TABLE delivery_dispute_messages IS
            'Sprint E4: 异议会话流水 — customer/merchant/platform/agent 四方消息';
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS delivery_dispute_messages CASCADE")
    op.execute("DROP TABLE IF EXISTS delivery_disputes CASCADE")
