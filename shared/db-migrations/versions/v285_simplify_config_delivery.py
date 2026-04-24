"""v206 — 简约配置交付系统基础表

为三层配置架构（业态模板 + DeliveryAgent + Agent动态策略）提供数据库支撑：

新建表：
  1. tenant_agent_configs    — 租户 Agent 策略配置 + 上线交付快照（JSONB）
  2. kds_display_rules       — KDS 分区显示规则（颜色/超时阈值/标识）
  3. member_migration_pending — 会员储值迁移待审核队列（天财→屯象）

用途：
  - tenant_agent_configs：onboarding import 写入，config_health 读取
  - kds_display_rules：健康度检查 + KDS 前端渲染规则
  - member_migration_pending：天财切换客户的会员储值安全迁移暂存

Revision ID: v206
Revises: v205
Create Date: 2026-04-11
"""

from alembic import op

revision = "v285"
down_revision = "v205"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. tenant_agent_configs ────────────────────────────────────────
    # 存储租户级别的 Agent 策略快照、业态类型和上线交付信息。
    # 每个租户只有一条记录（ON CONFLICT tenant_id DO UPDATE）。
    op.execute("""
        CREATE TABLE IF NOT EXISTS tenant_agent_configs (
            id                      BIGSERIAL PRIMARY KEY,
            tenant_id               UUID        NOT NULL,

            -- 业态类型（来自 DeliveryAgent 会话）
            restaurant_type         VARCHAR(50) NOT NULL DEFAULT 'casual_dining',

            -- Agent 策略快照（JSONB，来自 TenantConfigPackage.agent_policies）
            agent_policies          JSONB       NOT NULL DEFAULT '{}',

            -- 计费规则快照（最低消费/服务费，来自 TenantConfigPackage.billing_rules）
            billing_rules           JSONB       NOT NULL DEFAULT '{}',

            -- 激活的支付方式（JSONB 数组）
            payment_methods         JSONB       NOT NULL DEFAULT '[]',

            -- 激活的外卖渠道（JSONB 数组）
            channels_enabled        JSONB       NOT NULL DEFAULT '[]',

            -- 会员配置快照
            member_config           JSONB       NOT NULL DEFAULT '{}',

            -- 上线交付溯源
            onboarding_session_id   VARCHAR(100),
            migration_source        VARCHAR(50),     -- new | tiancai | pinzhi

            -- 配置健康度记录（最近一次检查结果）
            last_health_score       SMALLINT,
            last_health_checked_at  TIMESTAMPTZ,

            -- 标准字段
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN     NOT NULL DEFAULT FALSE,

            CONSTRAINT uq_tenant_agent_configs_tenant UNIQUE (tenant_id)
        )
    """)

    # RLS
    op.execute("ALTER TABLE tenant_agent_configs ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'tenant_agent_configs'
                  AND policyname = 'tenant_isolation_tenant_agent_configs'
            ) THEN
                CREATE POLICY tenant_isolation_tenant_agent_configs
                    ON tenant_agent_configs
                    USING (tenant_id = current_setting('app.tenant_id')::uuid)
                    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
            END IF;
        END $$
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_tenant_agent_configs_tenant
            ON tenant_agent_configs(tenant_id)
            WHERE is_deleted = false
    """)

    # ── 2. kds_display_rules ──────────────────────────────────────────
    # KDS 分区显示规则：颜色配置、超时阈值、标识开关。
    # 每个 (tenant_id, zone_code) 唯一。
    op.execute("""
        CREATE TABLE IF NOT EXISTS kds_display_rules (
            id                  BIGSERIAL   PRIMARY KEY,
            tenant_id           UUID        NOT NULL,
            store_id            UUID,                        -- NULL=全门店默认
            zone_code           VARCHAR(50) NOT NULL,        -- 档口代码：wok/cold/seafood
            zone_name           VARCHAR(100) NOT NULL,
            display_order       SMALLINT    NOT NULL DEFAULT 0,

            -- 超时阈值（分钟）
            alert_minutes       SMALLINT    NOT NULL DEFAULT 8,   -- 即将超时
            overdue_minutes     SMALLINT    NOT NULL DEFAULT 15,  -- 已超时

            -- 颜色（CSS hex）
            color_normal        VARCHAR(10) NOT NULL DEFAULT '#FFFFFF',
            color_warning       VARCHAR(10) NOT NULL DEFAULT '#FFC107',
            color_overdue       VARCHAR(10) NOT NULL DEFAULT '#F44336',

            -- 显示开关
            show_table_number   BOOLEAN     NOT NULL DEFAULT TRUE,
            show_guest_count    BOOLEAN     NOT NULL DEFAULT TRUE,
            show_waiter         BOOLEAN     NOT NULL DEFAULT FALSE,
            show_notes          BOOLEAN     NOT NULL DEFAULT TRUE,
            show_channel_badge  BOOLEAN     NOT NULL DEFAULT TRUE,  -- 外卖/堂食标识

            -- 催单闪烁
            blink_on_urge       BOOLEAN     NOT NULL DEFAULT TRUE,

            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN     NOT NULL DEFAULT FALSE,

            CONSTRAINT uq_kds_display_rules_zone
                UNIQUE (tenant_id, zone_code)
                DEFERRABLE INITIALLY DEFERRED
        )
    """)

    op.execute("ALTER TABLE kds_display_rules ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'kds_display_rules'
                  AND policyname = 'tenant_isolation_kds_display_rules'
            ) THEN
                CREATE POLICY tenant_isolation_kds_display_rules
                    ON kds_display_rules
                    USING (tenant_id = current_setting('app.tenant_id')::uuid)
                    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
            END IF;
        END $$
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_kds_display_rules_tenant
            ON kds_display_rules(tenant_id, display_order)
            WHERE is_deleted = false
    """)

    # ── 3. member_migration_pending ───────────────────────────────────
    # 天财→屯象会员迁移的储值余额审核暂存表。
    # 自动迁移只处理零余额会员；有余额的写入此表等待财务人工核实。
    op.execute("""
        CREATE TABLE IF NOT EXISTS member_migration_pending (
            id                      BIGSERIAL   PRIMARY KEY,
            tenant_id               UUID        NOT NULL,
            phone                   VARCHAR(20) NOT NULL,

            -- 天财原始数据快照
            display_name            VARCHAR(100),
            external_id_tiancai     VARCHAR(100),       -- 天财卡号
            stored_value_fen        BIGINT      NOT NULL DEFAULT 0, -- 待迁移储值（分）
            points                  BIGINT      NOT NULL DEFAULT 0,
            total_spend_fen         BIGINT      NOT NULL DEFAULT 0,
            tier_name               VARCHAR(50),
            source                  VARCHAR(50) NOT NULL DEFAULT 'tiancai_migration',

            -- 审核流程
            status                  VARCHAR(30) NOT NULL DEFAULT 'pending_review',
            -- pending_review / approved / rejected / migrated
            reviewed_by             VARCHAR(100),       -- 审核员工号
            reviewed_at             TIMESTAMPTZ,
            review_notes            TEXT,

            -- 迁移执行记录
            migrated_at             TIMESTAMPTZ,
            migration_error         TEXT,

            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN     NOT NULL DEFAULT FALSE,

            CONSTRAINT uq_member_migration_pending_phone
                UNIQUE (tenant_id, phone)
        )
    """)

    # 状态约束
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'chk_member_migration_pending_status'
            ) THEN
                ALTER TABLE member_migration_pending
                    ADD CONSTRAINT chk_member_migration_pending_status
                    CHECK (status IN (
                        'pending_review', 'approved', 'rejected', 'migrated', 'error'
                    ));
            END IF;
        END $$
    """)

    op.execute("ALTER TABLE member_migration_pending ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'member_migration_pending'
                  AND policyname = 'tenant_isolation_member_migration_pending'
            ) THEN
                CREATE POLICY tenant_isolation_member_migration_pending
                    ON member_migration_pending
                    USING (tenant_id = current_setting('app.tenant_id')::uuid)
                    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
            END IF;
        END $$
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_member_migration_pending_status
            ON member_migration_pending(tenant_id, status, created_at DESC)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_member_migration_pending_balance
            ON member_migration_pending(tenant_id, stored_value_fen DESC)
            WHERE status = 'pending_review' AND is_deleted = false
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS member_migration_pending")
    op.execute("DROP TABLE IF EXISTS kds_display_rules")
    op.execute("DROP TABLE IF EXISTS tenant_agent_configs")
