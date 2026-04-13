"""v253: point_transactions + point_rewards + horse_race_seasons + point_redemptions

员工积分持久化+赛马赛季+积分兑换完整表结构。

Revision ID: v253
Revises: v252
Create Date: 2026-04-13
"""
from alembic import op

revision = "v253"
down_revision = "v252"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── point_transactions — 积分流水表 ──────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS point_transactions (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            employee_id     UUID NOT NULL,
            employee_name   VARCHAR(100),
            store_id        UUID,
            rule_code       VARCHAR(50) NOT NULL,
            points          INT NOT NULL,
            balance_after   INT DEFAULT 0,
            reason          TEXT,
            source          VARCHAR(30) DEFAULT 'manual',
            operator_id     UUID,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            is_deleted      BOOLEAN DEFAULT FALSE
        );
    """)
    op.execute("""
        ALTER TABLE point_transactions ENABLE ROW LEVEL SECURITY;
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'point_transactions' AND policyname = 'point_transactions_tenant_isolation'
            ) THEN
                CREATE POLICY point_transactions_tenant_isolation ON point_transactions
                    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
            END IF;
        END $$;
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_point_transactions_tenant_employee
            ON point_transactions (tenant_id, employee_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_point_transactions_tenant_created
            ON point_transactions (tenant_id, created_at DESC);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_point_transactions_store
            ON point_transactions (tenant_id, store_id);
    """)

    # ── point_rewards — 积分兑换商品表 ──────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS point_rewards (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            reward_name     VARCHAR(100) NOT NULL,
            reward_type     VARCHAR(30) DEFAULT 'leave',
            points_cost     INT NOT NULL,
            stock           INT DEFAULT -1,
            description     TEXT,
            is_active       BOOLEAN DEFAULT TRUE,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW(),
            is_deleted      BOOLEAN DEFAULT FALSE
        );
    """)
    op.execute("""
        ALTER TABLE point_rewards ENABLE ROW LEVEL SECURITY;
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'point_rewards' AND policyname = 'point_rewards_tenant_isolation'
            ) THEN
                CREATE POLICY point_rewards_tenant_isolation ON point_rewards
                    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
            END IF;
        END $$;
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_point_rewards_tenant
            ON point_rewards (tenant_id, is_active);
    """)

    # ── horse_race_seasons — 赛马赛季表 ─────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS horse_race_seasons (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            season_name     VARCHAR(100) NOT NULL,
            scope_type      VARCHAR(20) DEFAULT 'store',
            scope_id        UUID,
            start_date      DATE NOT NULL,
            end_date        DATE NOT NULL,
            ranking_dimension VARCHAR(30) DEFAULT 'points',
            status          VARCHAR(20) DEFAULT 'upcoming',
            prizes          JSONB DEFAULT '[]',
            rules           JSONB DEFAULT '{}',
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW(),
            is_deleted      BOOLEAN DEFAULT FALSE
        );
    """)
    op.execute("""
        ALTER TABLE horse_race_seasons ENABLE ROW LEVEL SECURITY;
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'horse_race_seasons' AND policyname = 'horse_race_seasons_tenant_isolation'
            ) THEN
                CREATE POLICY horse_race_seasons_tenant_isolation ON horse_race_seasons
                    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
            END IF;
        END $$;
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_horse_race_seasons_tenant
            ON horse_race_seasons (tenant_id, status);
    """)

    # ── point_redemptions — 兑换记录表 ──────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS point_redemptions (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            employee_id     UUID NOT NULL,
            reward_id       UUID NOT NULL,
            points_spent    INT NOT NULL,
            status          VARCHAR(20) DEFAULT 'pending',
            approved_by     UUID,
            fulfilled_at    TIMESTAMPTZ,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            is_deleted      BOOLEAN DEFAULT FALSE
        );
    """)
    op.execute("""
        ALTER TABLE point_redemptions ENABLE ROW LEVEL SECURITY;
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'point_redemptions' AND policyname = 'point_redemptions_tenant_isolation'
            ) THEN
                CREATE POLICY point_redemptions_tenant_isolation ON point_redemptions
                    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
            END IF;
        END $$;
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_point_redemptions_tenant_employee
            ON point_redemptions (tenant_id, employee_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_point_redemptions_reward
            ON point_redemptions (tenant_id, reward_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS point_redemptions CASCADE;")
    op.execute("DROP TABLE IF EXISTS horse_race_seasons CASCADE;")
    op.execute("DROP TABLE IF EXISTS point_rewards CASCADE;")
    op.execute("DROP TABLE IF EXISTS point_transactions CASCADE;")
