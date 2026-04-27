"""v172 — 会员等级配置 + 积分体系

创建：
  member_level_configs   — 租户等级阶梯配置（普通/银卡/金卡/钻石）
  member_level_history   — 会员升降级历史记录
  points_rules           — 积分规则（按消费/生日/注册/推荐/签到）
  member_points_balance  — 会员当前积分余额

Revision: v172
"""

from alembic import op

revision = "v172"
down_revision = "v171"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS member_level_configs (
            id                      UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id               UUID        NOT NULL,
            level_code              VARCHAR(32) NOT NULL,
            level_name              VARCHAR(20) NOT NULL,
            min_points              INT         NOT NULL DEFAULT 0,
            min_annual_spend_fen    BIGINT      NOT NULL DEFAULT 0,
            discount_rate           NUMERIC(4,3) NOT NULL DEFAULT 1.0,
            birthday_bonus_multiplier NUMERIC(4,2) NOT NULL DEFAULT 1.0,
            priority_queue          BOOLEAN     NOT NULL DEFAULT FALSE,
            free_delivery           BOOLEAN     NOT NULL DEFAULT FALSE,
            sort_order              INT         NOT NULL DEFAULT 0,
            is_active               BOOLEAN     NOT NULL DEFAULT TRUE,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN     NOT NULL DEFAULT FALSE,
            UNIQUE (tenant_id, level_code)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_member_level_configs_tenant ON member_level_configs (tenant_id, sort_order)"
    )
    op.execute("ALTER TABLE member_level_configs ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY member_level_configs_rls ON member_level_configs
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)
    op.execute("ALTER TABLE member_level_configs FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE TABLE IF NOT EXISTS member_level_history (
            id              UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id       UUID        NOT NULL,
            member_id       UUID        NOT NULL,
            from_level      VARCHAR(32),
            to_level        VARCHAR(32) NOT NULL,
            trigger_type    VARCHAR(32) NOT NULL DEFAULT 'system',
            trigger_value   NUMERIC(12,2),
            note            TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN     NOT NULL DEFAULT FALSE
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_member_level_history_member ON member_level_history (tenant_id, member_id, created_at DESC)"
    )
    op.execute("ALTER TABLE member_level_history ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY member_level_history_rls ON member_level_history
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)
    op.execute("ALTER TABLE member_level_history FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE TABLE IF NOT EXISTS points_rules (
            id              UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id       UUID        NOT NULL,
            store_id        UUID,
            rule_name       VARCHAR(50) NOT NULL,
            earn_type       VARCHAR(32) NOT NULL,
            -- consumption / birthday / signup / referral / checkin
            points_per_100fen NUMERIC(8,2) NOT NULL DEFAULT 1.0,
            fixed_points    INT         NOT NULL DEFAULT 0,
            multiplier      NUMERIC(5,2) NOT NULL DEFAULT 1.0,
            valid_from      DATE,
            valid_until     DATE,
            is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN     NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_points_rules_tenant ON points_rules (tenant_id, earn_type, is_active)")
    op.execute("ALTER TABLE points_rules ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY points_rules_rls ON points_rules
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)
    op.execute("ALTER TABLE points_rules FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE TABLE IF NOT EXISTS member_points_balance (
            tenant_id       UUID        NOT NULL,
            member_id       UUID        NOT NULL,
            points          INT         NOT NULL DEFAULT 0,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, member_id)
        )
    """)
    op.execute("ALTER TABLE member_points_balance ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY member_points_balance_rls ON member_points_balance
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)
    op.execute("ALTER TABLE member_points_balance FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS member_points_balance")
    op.execute("DROP TABLE IF EXISTS points_rules")
    op.execute("DROP TABLE IF EXISTS member_level_history")
    op.execute("DROP TABLE IF EXISTS member_level_configs")
