"""v056b — 多渠道发布支持

新增表：
  channel_menu_items  — 菜品渠道映射（堂食/外卖-美团/外卖-饿了么/小程序/抖音）
  channel_pricing_rules — 渠道加价规则配置

新增列：
  dishes.lifecycle_stage — 菜品生命周期阶段
  dishes.lifecycle_changed_at — 生命周期最后变更时间

RLS 策略：标准安全模式（4操作 + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v056b
Revises: v055
Create Date: 2026-03-31
"""

from alembic import op

revision = "v056b"
down_revision = "v055"
branch_labels = None
depends_on = None

# 支持的渠道列表
CHANNELS = ("dine_in", "meituan", "eleme", "miniapp", "douyin")


def upgrade() -> None:
    # ──────────────────────────────────────────────────────────────────────
    # 1. channel_menu_items — 菜品渠道映射表
    # ──────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS channel_menu_items (
            id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID         NOT NULL,
            store_id         UUID         NOT NULL,
            dish_id          UUID         NOT NULL REFERENCES dishes(id),
            channel          VARCHAR(30)  NOT NULL,
            channel_price_fen INT,
            is_available     BOOLEAN      NOT NULL DEFAULT true,
            sort_order       INT          NOT NULL DEFAULT 0,
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, store_id, dish_id, channel)
        );
    """)
    op.execute("ALTER TABLE channel_menu_items ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE channel_menu_items FORCE ROW LEVEL SECURITY;")
    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(f"DROP POLICY IF EXISTS channel_menu_items_{action.lower()}_tenant ON channel_menu_items")
        _cond = "current_setting('app.tenant_id', TRUE) IS NOT NULL AND current_setting('app.tenant_id', TRUE) <> '' AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID"
        if action == "INSERT":
            op.execute(f"CREATE POLICY channel_menu_items_{action.lower()}_tenant ON channel_menu_items AS RESTRICTIVE FOR {action} WITH CHECK ({_cond})")
        else:
            op.execute(f"CREATE POLICY channel_menu_items_{action.lower()}_tenant ON channel_menu_items AS RESTRICTIVE FOR {action} USING ({_cond})")
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_channel_menu_items_store_channel
            ON channel_menu_items (tenant_id, store_id, channel);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_channel_menu_items_dish
            ON channel_menu_items (tenant_id, dish_id);
    """)

    # ──────────────────────────────────────────────────────────────────────
    # 2. channel_pricing_rules — 渠道加价规则
    # ──────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS channel_pricing_rules (
            id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID         NOT NULL,
            store_id         UUID         NOT NULL,
            channel          VARCHAR(30)  NOT NULL,
            rule_type        VARCHAR(20)  NOT NULL DEFAULT 'percent',
            value            NUMERIC(10,4) NOT NULL,
            description      TEXT,
            is_active        BOOLEAN      NOT NULL DEFAULT true,
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, store_id, channel)
        );
    """)
    op.execute("ALTER TABLE channel_pricing_rules ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE channel_pricing_rules FORCE ROW LEVEL SECURITY;")
    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(f"DROP POLICY IF EXISTS channel_pricing_rules_{action.lower()}_tenant ON channel_pricing_rules")
        _cond = "current_setting('app.tenant_id', TRUE) IS NOT NULL AND current_setting('app.tenant_id', TRUE) <> '' AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID"
        if action == "INSERT":
            op.execute(f"CREATE POLICY channel_pricing_rules_{action.lower()}_tenant ON channel_pricing_rules AS RESTRICTIVE FOR {action} WITH CHECK ({_cond})")
        else:
            op.execute(f"CREATE POLICY channel_pricing_rules_{action.lower()}_tenant ON channel_pricing_rules AS RESTRICTIVE FOR {action} USING ({_cond})")
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_channel_pricing_rules_store_channel
            ON channel_pricing_rules (tenant_id, store_id, channel)
            WHERE is_active = true;
    """)

    # ──────────────────────────────────────────────────────────────────────
    # 3. dishes — 新增生命周期字段
    # ──────────────────────────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE dishes
            ADD COLUMN IF NOT EXISTS lifecycle_stage VARCHAR(20) NOT NULL DEFAULT 'full',
            ADD COLUMN IF NOT EXISTS lifecycle_changed_at TIMESTAMPTZ;
    """)
    op.execute("""
        COMMENT ON COLUMN dishes.lifecycle_stage IS
            'research / testing / pilot / full / sunset / discontinued';
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_dishes_lifecycle_stage
            ON dishes (tenant_id, lifecycle_stage)
            WHERE is_deleted = false;
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_dishes_lifecycle_stage;")
    op.execute("ALTER TABLE dishes DROP COLUMN IF EXISTS lifecycle_changed_at;")
    op.execute("ALTER TABLE dishes DROP COLUMN IF EXISTS lifecycle_stage;")
    op.execute("DROP TABLE IF EXISTS channel_pricing_rules CASCADE;")
    op.execute("DROP TABLE IF EXISTS channel_menu_items CASCADE;")
