"""v097: 营销活动引擎 DB 化 — 将 campaign_engine.py 的内存存储迁移到 PostgreSQL

新建 3 张表：
  - campaigns             — 活动主表（含状态机/配置/预算/统计）
  - campaign_participants — 参与记录（per-customer 次数限制依赖此表）
  - campaign_rewards      — 奖励发放记录

设计要点：
  - stats 字段（participant_count/reward_count/total_cost_fen）内联到 campaigns，
    避免 JSONB 频繁读写，用原子 UPDATE + 1 保证并发安全
  - config/target_stores/target_segments/variants 存 JSONB（业务层控制结构）
  - campaign_participants 有 (tenant_id, campaign_id, customer_id) 索引，
    支持 check_eligibility 的参与次数限制查询
  - campaign_rewards 有 (tenant_id, campaign_id, reward_type) 索引，
    支持 analytics 的奖励类型分组统计

Revision ID: v097
Revises: v096
Create Date: 2026-04-01
"""

from alembic import op

revision = "v097"
down_revision = "v096"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. campaigns — 活动主表 ───────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID         NOT NULL,
            campaign_type     VARCHAR(50)  NOT NULL,
            name              VARCHAR(200) NOT NULL,
            description       TEXT,
            status            VARCHAR(20)  NOT NULL DEFAULT 'draft',
            config            JSONB        NOT NULL DEFAULT '{}',
            start_time        TIMESTAMPTZ,
            end_time          TIMESTAMPTZ,
            target_stores     JSONB        NOT NULL DEFAULT '[]',
            target_segments   JSONB        NOT NULL DEFAULT '[]',
            budget_fen        INT          NOT NULL DEFAULT 0,
            spent_fen         INT          NOT NULL DEFAULT 0,
            ab_test_id        UUID,
            variants          JSONB,
            participant_count INT          NOT NULL DEFAULT 0,
            reward_count      INT          NOT NULL DEFAULT 0,
            total_cost_fen    INT          NOT NULL DEFAULT 0,
            conversion_count  INT          NOT NULL DEFAULT 0,
            created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted        BOOLEAN      NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("ALTER TABLE campaigns ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY campaigns_rls ON campaigns
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_campaigns_tenant_status
            ON campaigns(tenant_id, status)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_campaigns_tenant_type
            ON campaigns(tenant_id, campaign_type, status)
            WHERE is_deleted = false
    """)

    # ── 2. campaign_participants — 参与记录 ───────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS campaign_participants (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            campaign_id     UUID        NOT NULL REFERENCES campaigns(id),
            customer_id     UUID        NOT NULL,
            trigger_event   JSONB       NOT NULL DEFAULT '{}',
            reward          JSONB       NOT NULL DEFAULT '{}',
            ab_variant      VARCHAR(50),
            participated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("ALTER TABLE campaign_participants ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY campaign_participants_rls ON campaign_participants
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_campaign_participants_customer
            ON campaign_participants(tenant_id, campaign_id, customer_id)
    """)

    # ── 3. campaign_rewards — 奖励发放记录 ───────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS campaign_rewards (
            id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID        NOT NULL,
            campaign_id UUID        NOT NULL REFERENCES campaigns(id),
            customer_id UUID        NOT NULL,
            reward_type VARCHAR(30) NOT NULL,
            reward_data JSONB       NOT NULL DEFAULT '{}',
            cost_fen    INT         NOT NULL DEFAULT 0,
            status      VARCHAR(20) NOT NULL DEFAULT 'granted',
            granted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("ALTER TABLE campaign_rewards ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY campaign_rewards_rls ON campaign_rewards
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_campaign_rewards_campaign
            ON campaign_rewards(tenant_id, campaign_id, reward_type)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS campaign_rewards CASCADE")
    op.execute("DROP TABLE IF EXISTS campaign_participants CASCADE")
    op.execute("DROP TABLE IF EXISTS campaigns CASCADE")
