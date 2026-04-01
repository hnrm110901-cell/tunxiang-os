"""v101: 拼团功能 — 活动 / 团队 / 成员三表

新建 3 张表：
  - group_buy_activities  — 拼团活动配置（商品/目标人数/价格/时限）
  - group_buy_teams       — 拼团团队（发起人/状态/过期时间）
  - group_buy_members     — 拼团成员（用户/订单/支付状态）

设计要点：
  - group_buy_teams.status 状态机：forming → succeeded / expired / cancelled
  - 使用 FOR UPDATE 行锁防止并发超员
  - 超时任务通过定时查询 expired_at < NOW() AND status='forming' 批量处理

Revision ID: v101
Revises: v100
Create Date: 2026-04-01
"""

from alembic import op

revision = "v101"
down_revision = "v100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. group_buy_activities — 拼团活动配置 ────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS group_buy_activities (
            id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID         NOT NULL,
            campaign_id         UUID,
            name                VARCHAR(200) NOT NULL,
            product_id          UUID         NOT NULL,
            product_name        VARCHAR(200),
            original_price_fen  INT          NOT NULL,
            group_price_fen     INT          NOT NULL,
            group_size          INT          NOT NULL DEFAULT 2,
            max_teams           INT          NOT NULL DEFAULT 100,
            time_limit_minutes  INT          NOT NULL DEFAULT 1440,
            status              VARCHAR(20)  NOT NULL DEFAULT 'draft',
            start_time          TIMESTAMPTZ,
            end_time            TIMESTAMPTZ,
            team_count          INT          NOT NULL DEFAULT 0,
            success_count       INT          NOT NULL DEFAULT 0,
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN      NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("ALTER TABLE group_buy_activities ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY group_buy_activities_rls ON group_buy_activities
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_group_buy_activities_tenant
            ON group_buy_activities(tenant_id, status)
            WHERE is_deleted = false
    """)

    # ── 2. group_buy_teams — 拼团团队 ────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS group_buy_teams (
            id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID         NOT NULL,
            activity_id       UUID         NOT NULL REFERENCES group_buy_activities(id),
            initiator_id      UUID         NOT NULL,
            target_size       INT          NOT NULL,
            current_size      INT          NOT NULL DEFAULT 1,
            status            VARCHAR(20)  NOT NULL DEFAULT 'forming',
            expired_at        TIMESTAMPTZ  NOT NULL,
            succeeded_at      TIMESTAMPTZ,
            created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted        BOOLEAN      NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("ALTER TABLE group_buy_teams ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY group_buy_teams_rls ON group_buy_teams
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_group_buy_teams_activity
            ON group_buy_teams(tenant_id, activity_id, status)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_group_buy_teams_expired
            ON group_buy_teams(expired_at)
            WHERE status = 'forming' AND is_deleted = false
    """)

    # ── 3. group_buy_members — 拼团成员 ──────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS group_buy_members (
            id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     UUID         NOT NULL,
            team_id       UUID         NOT NULL REFERENCES group_buy_teams(id),
            customer_id   UUID         NOT NULL,
            order_id      UUID,
            paid          BOOLEAN      NOT NULL DEFAULT FALSE,
            refunded      BOOLEAN      NOT NULL DEFAULT FALSE,
            joined_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted    BOOLEAN      NOT NULL DEFAULT FALSE,
            UNIQUE (team_id, customer_id)
        )
    """)
    op.execute("ALTER TABLE group_buy_members ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY group_buy_members_rls ON group_buy_members
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_group_buy_members_team
            ON group_buy_members(tenant_id, team_id)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS group_buy_members CASCADE")
    op.execute("DROP TABLE IF EXISTS group_buy_teams CASCADE")
    op.execute("DROP TABLE IF EXISTS group_buy_activities CASCADE")
