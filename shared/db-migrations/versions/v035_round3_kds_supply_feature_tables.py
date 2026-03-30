"""v035: Round 3 KDS增强+供应链补货+分区管理功能表

新增/修改表：
  dispatch_codes         — P0-A: 外卖出餐码（6位base62）
  store_push_configs     — P1-B: 门店出单模式配置（immediate/post_payment）
  kds_tasks (ALTER)      — P1-B: 新增 called_at/served_at/call_count，状态机扩展 'calling'
  booking_prep_tasks     — P1-C: 预订备餐任务（档口级备料任务）
  inventory_thresholds   — P1-D: 目标库存双规则补货阈值配置
  delivery_orders (ALTER)— P2-A: 新增 is_new_customer 字段（新客打标）

RLS 策略：
  全部使用 v006+ 标准安全模式（4操作 + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v035
Revises: v034
Create Date: 2026-03-30
"""

from alembic import op

revision = "v035"
down_revision = "v034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # P0-A: dispatch_codes — 外卖出餐码
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS dispatch_codes (
            id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id    UUID        NOT NULL,
            order_id     UUID        NOT NULL,
            code         TEXT        NOT NULL,
            platform     TEXT        NOT NULL DEFAULT 'unknown',
            confirmed    BOOLEAN     NOT NULL DEFAULT FALSE,
            confirmed_at TIMESTAMPTZ,
            operator_id  UUID,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(tenant_id, order_id),
            UNIQUE(tenant_id, code)
        );
    """)
    op.execute("ALTER TABLE dispatch_codes ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE dispatch_codes FORCE ROW LEVEL SECURITY;")
    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(f"""
            CREATE POLICY dispatch_codes_{action.lower()}_tenant ON dispatch_codes
            AS RESTRICTIVE FOR {action}
            USING (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
        """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_dispatch_codes_tenant_order
            ON dispatch_codes (tenant_id, order_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_dispatch_codes_tenant_code
            ON dispatch_codes (tenant_id, code);
    """)

    # ─────────────────────────────────────────────────────────────────
    # P1-B: store_push_configs — 出单模式配置
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS store_push_configs (
            id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id  UUID        NOT NULL,
            store_id   UUID        NOT NULL,
            push_mode  TEXT        NOT NULL DEFAULT 'immediate',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(tenant_id, store_id)
        );
    """)
    op.execute("ALTER TABLE store_push_configs ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE store_push_configs FORCE ROW LEVEL SECURITY;")
    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(f"""
            CREATE POLICY store_push_configs_{action.lower()}_tenant ON store_push_configs
            AS RESTRICTIVE FOR {action}
            USING (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
        """)

    # ─────────────────────────────────────────────────────────────────
    # P1-B: kds_tasks ALTER — 等叫状态机扩展
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE kds_tasks
            ADD COLUMN IF NOT EXISTS called_at  TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS served_at  TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS call_count INT NOT NULL DEFAULT 0;
    """)
    # 扩展 status CHECK 约束，新增 'calling' 值
    op.execute("ALTER TABLE kds_tasks DROP CONSTRAINT IF EXISTS kds_tasks_status_check;")
    op.execute("""
        ALTER TABLE kds_tasks ADD CONSTRAINT kds_tasks_status_check
            CHECK (status IN ('pending', 'cooking', 'calling', 'done', 'cancelled'));
    """)

    # ─────────────────────────────────────────────────────────────────
    # P1-C: booking_prep_tasks — 预订备餐任务
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS booking_prep_tasks (
            id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     UUID        NOT NULL,
            booking_id    UUID        NOT NULL,
            store_id      UUID        NOT NULL,
            dish_id       UUID        NOT NULL,
            dish_name     TEXT        NOT NULL,
            quantity      INT         NOT NULL DEFAULT 1,
            dept_id       TEXT,
            prep_start_at TIMESTAMPTZ,
            status        TEXT        NOT NULL DEFAULT 'pending',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(tenant_id, booking_id, dish_id)
        );
    """)
    op.execute("ALTER TABLE booking_prep_tasks ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE booking_prep_tasks FORCE ROW LEVEL SECURITY;")
    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(f"""
            CREATE POLICY booking_prep_tasks_{action.lower()}_tenant ON booking_prep_tasks
            AS RESTRICTIVE FOR {action}
            USING (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
        """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_booking_prep_tasks_tenant_booking
            ON booking_prep_tasks (tenant_id, booking_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_booking_prep_tasks_tenant_status
            ON booking_prep_tasks (tenant_id, status);
    """)

    # ─────────────────────────────────────────────────────────────────
    # P1-D: inventory_thresholds — 目标库存双规则补货阈值
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS inventory_thresholds (
            id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     UUID         NOT NULL,
            store_id      UUID         NOT NULL,
            ingredient_id UUID         NOT NULL,
            safety_stock  NUMERIC(12,3) NOT NULL DEFAULT 0,
            target_stock  NUMERIC(12,3) NOT NULL DEFAULT 0,
            min_order_qty NUMERIC(12,3) NOT NULL DEFAULT 1,
            trigger_rule  TEXT         NOT NULL DEFAULT 'safety_only',
            updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            UNIQUE(tenant_id, store_id, ingredient_id)
        );
    """)
    op.execute("ALTER TABLE inventory_thresholds ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE inventory_thresholds FORCE ROW LEVEL SECURITY;")
    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(f"""
            CREATE POLICY inventory_thresholds_{action.lower()}_tenant ON inventory_thresholds
            AS RESTRICTIVE FOR {action}
            USING (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
        """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_inventory_thresholds_tenant_store
            ON inventory_thresholds (tenant_id, store_id);
    """)

    # ─────────────────────────────────────────────────────────────────
    # P2-A: delivery_orders ALTER — 新客打标
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE delivery_orders
            ADD COLUMN IF NOT EXISTS is_new_customer BOOLEAN NOT NULL DEFAULT FALSE;
    """)


def downgrade() -> None:
    # P2-A
    op.execute("ALTER TABLE delivery_orders DROP COLUMN IF EXISTS is_new_customer;")

    # P1-D
    op.execute("DROP TABLE IF EXISTS inventory_thresholds;")

    # P1-C
    op.execute("DROP TABLE IF EXISTS booking_prep_tasks;")

    # P1-B kds_tasks revert
    op.execute("ALTER TABLE kds_tasks DROP CONSTRAINT IF EXISTS kds_tasks_status_check;")
    op.execute("""
        ALTER TABLE kds_tasks ADD CONSTRAINT kds_tasks_status_check
            CHECK (status IN ('pending', 'cooking', 'done', 'cancelled'));
    """)
    op.execute("ALTER TABLE kds_tasks DROP COLUMN IF EXISTS called_at;")
    op.execute("ALTER TABLE kds_tasks DROP COLUMN IF EXISTS served_at;")
    op.execute("ALTER TABLE kds_tasks DROP COLUMN IF EXISTS call_count;")

    # P1-B
    op.execute("DROP TABLE IF EXISTS store_push_configs;")

    # P0-A
    op.execute("DROP TABLE IF EXISTS dispatch_codes;")
